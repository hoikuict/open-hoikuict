"""Check only the isolated preview, not production authorization."""
from tools.monthly_assignment_preview import AssignmentPreview


def main():
    preview = AssignmentPreview()
    client = preview.fixture.client
    checked = []
    try:
        def actor(key, dataset="partial"):
            response = client.post("/preview/state", json={"actor": key, "dataset": dataset})
            assert response.status_code == 200, response.text

        for key, classroom, month, expected in (
            ("teacher_a", 1, "2026-10", True), ("teacher_a", 2, "2026-10", False),
            ("teacher_a", 1, "2026-11", False), ("teacher_b", 2, "2026-10", True),
            ("teacher_b", 2, "2026-09", False), ("support", 1, "2026-10", True),
            ("support", 2, "2026-10", True), ("temporary", 1, "2026-10", True),
            ("temporary", 1, "2026-11", False), ("unassigned", 1, "2026-10", False),
            ("admin_none", 1, "2026-10", False), ("admin_a", 1, "2026-10", True),
            ("admin_a", 2, "2026-10", False), ("viewer", 1, "2026-10", False),
        ):
            actor(key)
            context = preview.fixture.context(month, 1, classroom).json()
            assert context["editable"] == expected, (key, classroom, month)
            response = preview.fixture.save(preview.fixture.payload(context))
            assert response.status_code == (200 if expected else 403), response.text
        checked.append("14 actor/class/month combinations: context and direct save")

        actor("teacher_a")
        context = preview.fixture.context().json()
        payload = preview.fixture.payload(context, {"child:1:life": {"body": "保存を拒否する確認入力"}})
        assert client.post("/preview/revoke", json={}).status_code == 200
        response = preview.fixture.save(payload)
        assert response.status_code == 403 and "解除" in response.json()["detail"]
        after = preview.fixture.context().json()
        assert after["sheet"]["fields"] == context["sheet"]["fields"]
        assert after["lock_version"] == context["lock_version"]
        assert client.post("/preview/restore", json={}).status_code == 200
        assert preview.fixture.save(payload).status_code == 200
        checked.append("revoked assignment refuses write without changing saved data; restore permits save")

        actor("admin_none")
        context = preview.fixture.context().json()
        export = {key: context[key] for key in ("document_id", "lock_version", "classroom_id", "target_month", "age")}
        response = client.post("/plans/monthly-library/export", json=export | {"kind": "xlsx", "mode": "saved"})
        assert response.status_code == 200 and response.content[:2] == b"PK", response.text[:100]
        response = client.post("/plans/monthly-library/export", json=export | {"kind": "xlsx", "mode": "current",
            "owner_name": context["owner_name"], "fields": {}})
        assert response.status_code == 403
        checked.append("unassigned admin can export saved Excel but cannot submit unsaved text")

        actor("teacher_a", "approved")
        context = preview.fixture.context().json()
        assert context["editable"] is False
        assert context["preview_peer_names"] == []
        assert preview.fixture.save(preview.fixture.payload(context)).status_code == 409
        actor("teacher_a", "empty")
        context = preview.fixture.context().json()
        assert context["document_id"] is None and context["sheet"]["fields"] == {}
        for age in range(6):
            context = preview.fixture.context(age=age).json()
            assert context["definitions"] and not context["ai"]["enabled"]
        assert client.get("/preview").status_code == 200
        assert client.get("/preview/ui.js").status_code == 200
        assert client.get("/preview/presence.js").status_code == 200
        assert "架空職員A" not in context["preview_peer_names"]
        assert preview.fixture.context("2026-07").json()["preview_peer_names"] == []
        assert client.get("/plans/documents/1").status_code == 404
        checked.append("approved/new/all six ages; AI disabled; unrelated routes blocked")
        print("PASS\n" + "\n".join(checked))
    finally:
        preview.close()


if __name__ == "__main__":
    main()
