from __future__ import annotations

import re
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import _clear_login_failures, current_user, hash_password
from app.main import app
from app.models import Asset, Company, FixedReportContent, PipeSection, Project, ReportTemplate, SignupInvitation, User
from app.reports import render_report_html, render_report_pdf
from app.seed import seed_demo_data
from app.storage import LocalAssetStorage


def _create_project(client, identities, code: str = "GENERATOR-001", **fields):
    payload = {
        "company_id": str(identities["company"].id),
        "project_code": code,
        "project_name": "Drainage Survey",
        **fields,
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_company_project_and_pipe_crud_without_inspections(client, identities):
    company = client.post("/api/companies", json={"company_name": "Synthetic CRUD Company"})
    assert company.status_code == 201
    company_id = company.json()["id"]
    assert client.get(f"/api/companies/{company_id}").json()["company_name"] == "Synthetic CRUD Company"
    assert client.patch(f"/api/companies/{company_id}", json={"phone": "+852 1234 5678"}).json()["phone"] == "+852 1234 5678"
    assert len(client.get("/api/companies").json()["items"]) == 2

    project = _create_project(client, identities, code="CRUD-001", project_name="CRUD Demo", client_name="Sample Client", location="Test Site", report_date="2026-01-10", tv_reference_no="TV-CRUD-1")
    project_id = project["id"]
    assert client.get(f"/api/projects/{project_id}").json()["project_code"] == "CRUD-001"
    assert client.patch(f"/api/projects/{project_id}", json={"status": "IN_PROGRESS"}).json()["status"] == "IN_PROGRESS"

    pipe = client.post("/api/pipe-sections", json={"project_id": project_id, "pipe_id": "P-01", "section_reference": "MH1-MH2", "survey_length_m": 26.25, "survey_status": "COMPLETED"})
    assert pipe.status_code == 201
    pipe_id = pipe.json()["id"]
    assert client.get(f"/api/pipe-sections/{pipe_id}").json()["pipe_id"] == "P-01"
    assert client.patch(f"/api/pipe-sections/{pipe_id}", json={"remarks": "Synthetic update"}).json()["remarks"] == "Synthetic update"

    assert client.get("/api/inspections").status_code == 404
    assert client.delete(f"/api/pipe-sections/{pipe_id}").status_code == 204
    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    assert client.delete(f"/api/companies/{company_id}").status_code == 204


def test_user_and_asset_crud(client, identities):
    company_id = str(identities["company"].id)
    user = client.post("/api/users", json={"company_id": company_id, "full_name": "New Operator", "email": f"new-{uuid4()}@example.test", "role": "OPERATOR"})
    assert user.status_code == 201
    user_id = user.json()["id"]
    assert client.get(f"/api/users/{user_id}").json()["role"] == "OPERATOR"
    assert client.patch(f"/api/users/{user_id}", json={"full_name": "New Operator Two"}).json()["full_name"] == "New Operator Two"
    assert client.delete(f"/api/users/{user_id}").status_code == 204
    asset = client.post("/api/assets", json={"company_id": company_id, "file_name": "sample-plan.pdf", "file_type": "PDF", "sha256_hash": "a" * 64, "metadata_json": {"synthetic": True}})
    assert asset.status_code == 201
    asset_id = asset.json()["id"]
    assert client.get(f"/api/assets/{asset_id}").json()["sha256_hash"] == "a" * 64
    assert client.patch(f"/api/assets/{asset_id}", json={"file_type": "SITE_PLAN"}).json()["file_type"] == "SITE_PLAN"
    assert client.delete(f"/api/assets/{asset_id}").status_code == 204


def test_pydantic_validation_and_viewer_rbac(client, identities):
    invalid = client.post("/api/projects", json={"project_code": "MISSING-COMPANY", "project_name": "Invalid"})
    assert invalid.status_code == 422
    app.dependency_overrides[current_user] = lambda: identities["viewer"]
    denied = client.post("/api/companies", json={"company_name": "Not allowed"})
    assert denied.status_code == 403
    assert client.get("/api/companies").status_code == 200


def test_dashboard_aggregates_seed_data(client, db: Session):
    ids = seed_demo_data(db)
    project = db.get(Project, UUID(ids["project_id"]))
    company = db.get(Company, UUID(ids["company_id"]))
    assert project is not None and company is not None
    assert project.company_id == company.id
    assert company.default_report_language == "en"
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["totals"]["projects"] == 1
    assert payload["totals"]["pipe_sections"] == 0
    assert not payload["pipe_sections_by_status"]
    assert ids["project_id"] == payload["projects"][0]["id"]


def test_local_auth_mode_skips_manus_oauth(client, db: Session, monkeypatch):
    seed_demo_data(db)
    monkeypatch.setenv("CCTV_AUTH_MODE", "local")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CCTV_LOCAL_AUTH_EMAIL", "admin@example.test")

    with TestClient(app, client=("127.0.0.1", 8000)) as local_client:
        session = local_client.get("/api/auth/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True
        assert session.json()["auth_mode"] == "local-demo"

        login = local_client.get("/api/auth/login", follow_redirects=False)
        assert login.status_code == 303
        assert login.headers["location"] == "/"


def test_password_auth_login_password_management_and_logout(client, db: Session, identities, monkeypatch):
    seed_demo_data(db)
    monkeypatch.setenv("CCTV_AUTH_MODE", "password")
    monkeypatch.setenv("CCTV_AUTH_SECRET", "test-only-signing-secret-with-at-least-32-characters")
    app.dependency_overrides.pop(current_user, None)
    admin = identities["admin"]
    admin.password_hash = hash_password("Correct Horse Battery! 2026")
    db.commit()
    _clear_login_failures(admin.email)
    password_client = TestClient(app, client=("127.0.0.1", 8000))

    anonymous = password_client.get("/api/auth/session")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"authenticated": False, "auth_mode": "password"}
    wrong_password = password_client.post("/api/auth/login", json={"email": admin.email, "password": "incorrect password"})
    assert wrong_password.status_code == 401
    assert wrong_password.json()["detail"] == "Email or password is incorrect."

    login = password_client.post("/api/auth/login", json={"email": admin.email, "password": "Correct Horse Battery! 2026"})
    assert login.status_code == 204
    assert "httponly" in login.headers["set-cookie"].lower()
    session = password_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["email"] == admin.email
    assert session.json()["auth_mode"] == "password"

    updated_password = "A Different Secure Password 2026"
    cross_origin_update = password_client.put(
        f"/api/auth/users/{identities['viewer'].id}/password",
        json={"password": updated_password},
        headers={"Origin": "https://attacker.example"},
    )
    assert cross_origin_update.status_code == 403
    update = password_client.put(f"/api/auth/users/{identities['viewer'].id}/password", json={"password": updated_password})
    assert update.status_code == 204
    listed_users = password_client.get("/api/users")
    assert listed_users.status_code == 200
    assert all("password_hash" not in row for row in listed_users.json()["items"])

    for _ in range(5):
        assert password_client.post("/api/auth/login", json={"email": admin.email, "password": "incorrect password"}).status_code == 401
    throttled = password_client.post("/api/auth/login", json={"email": admin.email, "password": "incorrect password"})
    assert throttled.status_code == 429

    logout = password_client.post("/api/auth/logout", follow_redirects=False)
    assert logout.status_code == 303
    password_client.cookies.clear()
    assert password_client.get("/api/auth/session").json() == {"authenticated": False, "auth_mode": "password"}
    _clear_login_failures(admin.email)


def test_password_signup_uses_single_use_workspace_invitation(client, db: Session, identities, monkeypatch):
    monkeypatch.setenv("CCTV_AUTH_MODE", "password")
    monkeypatch.setenv("CCTV_AUTH_SECRET", "test-only-signing-secret-with-at-least-32-characters")
    app.dependency_overrides.pop(current_user, None)

    admin = identities["admin"]
    admin.password_hash = hash_password("Correct Horse Battery! 2026")
    db.commit()
    admin_client = TestClient(app, client=("127.0.0.1", 8000))
    login = admin_client.post("/api/auth/login", json={"email": admin.email, "password": "Correct Horse Battery! 2026"})
    assert login.status_code == 204

    invitation_response = admin_client.post("/api/auth/invitations", json={})
    assert invitation_response.status_code == 201
    invitation = invitation_response.json()
    assert invitation["code"]
    stored_invitation = db.scalar(select(SignupInvitation))
    assert stored_invitation is not None
    assert stored_invitation.code_hash != invitation["code"]

    signup_client = TestClient(app, client=("127.0.0.1", 8000))
    payload = {
        "invite_code": invitation["code"],
        "full_name": "New Workspace Member",
        "email": "new-member@example.test",
        "password": "A Strong Password 2026!",
    }
    invalid_invite = signup_client.post("/api/auth/signup", json={**payload, "invite_code": "invalid-code-that-is-long-enough"})
    assert invalid_invite.status_code == 400
    signup = signup_client.post("/api/auth/signup", json=payload)
    assert signup.status_code == 204
    assert "httponly" in signup.headers["set-cookie"].lower()

    session = signup_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["email"] == payload["email"]
    created_user = db.scalar(select(User).where(User.email == payload["email"]))
    assert created_user is not None
    assert created_user.company_id == admin.company_id
    assert created_user.role == "VIEWER"
    assert created_user.password_hash != payload["password"]

    reused_invite = TestClient(app, client=("127.0.0.1", 8000)).post(
        "/api/auth/signup",
        json={**payload, "email": "second-member@example.test"},
    )
    assert reused_invite.status_code == 400

    cross_origin = TestClient(app, client=("127.0.0.1", 8000)).post(
        "/api/auth/signup",
        json={**payload, "invite_code": invitation["code"], "email": "third-member@example.test"},
        headers={"Origin": "https://attacker.example"},
    )
    assert cross_origin.status_code == 403


def test_report_contains_reference_copy_english_order_and_pdf(client, db: Session):
    ids = seed_demo_data(db)
    html = render_report_html(db, ids["project_id"])
    assert "CCTV Survey Report" in html and "Harbour View Drainage Survey" in html
    assert 'class="company-logo"' in html and "data:image/png;base64," in html
    assert 'alt="Northstar Drainage Services (Synthetic) logo"' in html
    cover = html.split('<section class="cover" id="section-cover">', 1)[1].split("</section>", 1)[0]
    assert 'class="cover-background"' in cover and 'src="data:image/png;base64,' in cover
    assert 'class="cover-background"' not in html.split("</section>", 1)[1]
    assert "This is to certify that qualified personnel have undertaken the coding for this Variation Order" in html
    assert "The machine run along the pipeline and the image is transmitted to the console unit" in html
    assert "The grading and coding in the report is referred to Manual of Sewer Condition Classification 5th Edition (MSCC (5th Edition))" not in html
    assert "The grading and coding in the report is referred to Manual of Sewer Condition Classification 5th Edition (MSCC 5th Edition)" in html
    assert "Contents</h1>" in html
    markers = (
        'id="section-cover"', 'id="section-eusr-certificate"', 'id="section-contents"',
        'id="section-introduction"', 'id="section-method-statement"', 'id="section-summary"',
        'id="section-recommendations"', 'id="section-conclusion"', 'id="section-appendices"',
    )
    offsets = [html.index(marker) for marker in markers]
    assert offsets == sorted(offsets)
    assert "Grade 3: Best practice suggests consideration should be given to maintenance activities in the medium term." in html
    assert "Grade 5: Best practice suggests that this pipe is at a high risk of backing up or causing flooding." in html
    assert "Material Types" in html and "Vitrified Clay" in html and "Ductile Iron" in html
    assert "II-D Detailed Section Report" not in html and "Video Files" not in html
    assert "5) Conclusion" in html
    assert not re.search(r"[\u4e00-\u9fff]", html)
    pdf = render_report_pdf(db, ids["project_id"])
    assert pdf.startswith(b"%PDF-") and len(pdf) > 4000


def test_video_and_defect_entry_surfaces_are_removed():
    resource_config = (Path(__file__).parents[2] / "frontend/src/lib/resources.ts").read_text(encoding="utf-8")
    app_routes = (Path(__file__).parents[2] / "frontend/src/App.tsx").read_text(encoding="utf-8")
    report_page = (Path(__file__).parents[2] / "frontend/src/pages/ReportPreview.tsx").read_text(encoding="utf-8")
    assert "inspections:" not in resource_config
    assert "video_asset_id" not in resource_config
    assert 'path="/defects"' not in app_routes
    assert "uploadSurveyBatch" not in report_page
    assert "Select WinCan PDF" in report_page


def test_wincan_pipe_row_parser_and_report_recommendations(client, db: Session, identities):
    from app.wincan_report import parse_wincan_pipe_rows

    extracted = """
Pipe ID: P-100
Section reference: MH-1 to MH-2
Start node: MH-1
End node: MH-2
Length: 25.60 m
Material: VC
Condition grade: 4
Defect description: Settled deposits and longitudinal cracks
Site environment: Residential road
Recommendation: Clean and rehabilitate
"""
    rows = parse_wincan_pipe_rows(extracted)
    assert len(rows) == 1
    assert rows[0]["pipe_id"] == "P-100"
    assert rows[0]["survey_length_m"] == "25.60"
    assert rows[0]["defects_summary"] == "Settled deposits and longitudinal cracks"
    tabular = """
Pipe ID       Start MH      Finish MH      Length (m)      Material      Grade      Defect
P-101         MH-10         MH-11          12.5            Vitrified Clay    4          Fracture
"""
    table_rows = parse_wincan_pipe_rows(tabular)
    assert len(table_rows) == 1
    assert table_rows[0]["pipe_id"] == "P-101"
    assert table_rows[0]["pipe_material_code"] == "VC"
    assert table_rows[0]["condition_grade"] == "4"

    project = _create_project(
        client,
        identities,
        code="WINCAN-001",
        project_name="WinCan Import Test",
        location="Test Location",
        survey_start_date="2026-10-01",
        survey_end_date="2026-10-31",
    )
    response = client.post(f"/api/projects/{project['id']}/wincan-report", json={"rows": rows})
    assert response.status_code == 200, response.text
    assert response.json() == {"count": 1, "created": 1, "updated": 0}
    report_html = client.get(f"/api/projects/{project['id']}/report.html").text
    assert "25.60" in report_html and "Residential road" in report_html
    assert "Mechanical Cleaning: A total of 1 pipe sections (Pipe ID: P-100)" in report_html
    assert "CIPP Rehabilitation: A total of 1 pipe sections (Pipe ID: P-100)" in report_html
    assert "Between 01/10/2026 and 31/10/2026 (October 2026)" in report_html


def test_wincan_pdf_preview_rejects_invalid_pdf_and_extracts_text(client, identities, db: Session):
    project = _create_project(client, identities, code="WINCAN-PDF-001", project_name="PDF Text Extraction")
    invalid = client.post(
        f"/api/projects/{project['id']}/wincan-report/preview",
        files={"file": ("report.pdf", b"not a pdf", "application/pdf")},
    )
    assert invalid.status_code == 422
    assert "valid PDF" in invalid.json()["detail"]
    generated_pdf = render_report_pdf(db, project["id"])
    preview = client.post(
        f"/api/projects/{project['id']}/wincan-report/preview",
        files={"file": ("wincan.pdf", generated_pdf, "application/pdf")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["page_count"] >= 1
    assert "PDF Text Extraction" in preview.json()["text_preview"]


def test_postgres_url_normalization():
    from app.database import normalize_database_url

    assert normalize_database_url("postgresql://user:secret@localhost/db").startswith("postgresql+psycopg://")
    assert normalize_database_url("mysql://user:secret@localhost/db").startswith("mysql+pymysql://")


def test_report_download_updates_status(client, identities):
    project = Project(company_id=identities["company"].id, project_code="PDF-001", project_name="PDF Test", report_date=date(2026, 2, 1), status="DRAFT", report_status="DRAFT")
    from app.database import get_db

    session = app.dependency_overrides[get_db]()
    session.add(project)
    session.commit()
    template = ReportTemplate(company_id=project.company_id, template_name="Test Template", is_active=True, is_default=True, language="en")
    session.add(template)
    session.flush()
    session.add(FixedReportContent(template_id=template.id, section_code="intro", title="Introduction", content_template="Sample introduction", display_order=1, version=1))
    session.commit()
    response = client.get(f"/api/projects/{project.id}/report.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert session.get(Project, project.id).report_status == "GENERATED"


def test_local_storage_stream_hash_and_path_safety(tmp_path):
    storage = LocalAssetStorage(tmp_path)
    saved = storage.save("frame.jpg", BytesIO(b"synthetic-frame"), "project-123")
    assert saved.file_size_bytes == 15
    assert len(saved.sha256_hash) == 64
    with storage.open(saved.storage_key) as stream:
        assert stream.read() == b"synthetic-frame"
    try:
        storage.open("../../etc/passwd")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal key was accepted")


def signed_session(email: str, open_id: str) -> str:
    import jwt
    import os

    return jwt.encode({"appId": os.environ["MANUS_PROJECT_ID"], "openId": open_id, "email": email, "name": email.split("@")[0]}, os.environ["MANUS_JWT_SECRET"], algorithm="HS256")


def test_valid_manus_session_bootstraps_first_admin_then_viewer(client, identities, monkeypatch):
    monkeypatch.delenv("CCTV_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("MANUS_PROJECT_ID", "cctv-phase-one-test")
    monkeypatch.setenv("MANUS_JWT_SECRET", "phase-one-only-test-secret")
    app.dependency_overrides.pop(current_user, None)
    client.cookies.set("webdev_app_session", signed_session("first.admin@customer.invalid", "manus-first-admin"))
    first = client.get("/api/auth/session")
    assert first.status_code == 200 and first.json()["user"]["role"] == "ADMIN"
    assert client.post("/api/companies", json={"company_name": "First Admin Company"}).status_code == 201
    client.cookies.set("webdev_app_session", signed_session("second.viewer@customer.invalid", "manus-second-viewer"))
    second = client.get("/api/auth/session")
    assert second.status_code == 200 and second.json()["user"]["role"] == "VIEWER"
    assert client.get("/api/companies").status_code == 200
    assert client.post("/api/companies", json={"company_name": "Viewer Cannot Create"}).status_code == 403


def test_configured_admin_email_prevents_first_user_privilege_escalation(client, identities, monkeypatch):
    monkeypatch.setenv("MANUS_PROJECT_ID", "cctv-phase-one-test")
    monkeypatch.setenv("MANUS_JWT_SECRET", "phase-one-only-test-secret")
    monkeypatch.setenv("CCTV_ADMIN_EMAIL", "designated.admin@customer.invalid")
    app.dependency_overrides.pop(current_user, None)
    client.cookies.set("webdev_app_session", signed_session("other.user@customer.invalid", "manus-other-user"))
    assert client.get("/api/auth/session").json()["user"]["role"] == "VIEWER"
    client.cookies.set("webdev_app_session", signed_session("designated.admin@customer.invalid", "manus-designated-admin"))
    assert client.get("/api/auth/session").json()["user"]["role"] == "ADMIN"


def test_video_upload_and_defect_event_api_routes_are_removed(client, identities):
    project = _create_project(client, identities, code="VIDEO-REMOVED")
    project_id = project["id"]
    assert client.get("/api/inspections").status_code == 404
    video_asset = client.post("/api/assets", json={
        "company_id": str(identities["company"].id),
        "project_id": project_id,
        "file_name": "sample.mp4",
        "file_type": "VIDEO",
    })
    assert video_asset.status_code == 422
    assert client.get(f"/api/projects/{project_id}/videos").status_code == 404
    assert client.post(f"/api/projects/{project_id}/videos", files={"file": ("sample.mp4", b"video", "video/mp4")}).status_code == 405
    assert client.post(f"/api/projects/{project_id}/filename-preview", json={"filenames": ["sample.mp4"]}).status_code == 405
    assert client.post(f"/api/projects/{project_id}/survey-batch", data={"metadata_json": "[]"}).status_code == 405
    assert client.get(f"/api/projects/{project_id}/events").status_code == 404


def test_site_plan_upload_requires_real_image_and_report_embeds_it(client, identities):
    project = _create_project(client, identities, code="PLAN-001")
    output = BytesIO()
    Image.new("RGB", (320, 240), color=(25, 80, 125)).save(output, format="PNG")
    plan_bytes = output.getvalue()
    uploaded = client.post(f"/api/projects/{project['id']}/site-plans", files={"file": ("layout.png", plan_bytes, "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["file_type"] == "SITE_PLAN"
    assert client.get(f"/api/projects/{project['id']}/site-plans").json()["items"][0]["file_name"] == "layout.png"
    bad = client.post(f"/api/projects/{project['id']}/site-plans", files={"file": ("spoofed.png", b"not an image", "image/png")})
    assert bad.status_code == 422
    html = client.get(f"/api/projects/{project['id']}/report.html").text
    assert "layout.png" in html and "data:image/png;base64," in html
