"""Build offline screenshot fixtures from the deployed child list and detail templates."""
import ast
import shutil
from datetime import date
from types import SimpleNamespace

from build_capture import CAPTURE, DEPLOYED, REVIEW, offline, render


def constants(file_name, names):
    result = {}
    for node in ast.parse((DEPLOYED / file_name).read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            if key in names:
                result[key] = ast.literal_eval(node.value)
    return result


class ExampleChild(SimpleNamespace):
    def get_field(self, key):
        if key == "classroom":
            return self.classroom.name
        return getattr(self, key, "")


def example(child_id, family_name, name, classroom, birthday):
    return ExampleChild(
        id=child_id, last_name="見本", first_name=name, full_name=f"見本 {name}",
        last_name_kana="ミホン", first_name_kana="アオイ" if name == "あおい" else "ヒナタ",
        full_name_kana="ミホン " + ("アオイ" if name == "あおい" else "ヒナタ"),
        classroom=SimpleNamespace(name=classroom), birth_date=date.fromisoformat(birthday),
        sex=SimpleNamespace(label="未設定"), status=SimpleNamespace(value="enrolled", label="在園"),
        family=SimpleNamespace(family_name=family_name, display_code=f"F-{child_id:05d}"),
        age=4 if name == "あおい" else 3, enrollment_date=date(2025, 4, 1),
    )


def main():
    CAPTURE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REVIEW.parents[1] / "dist/assets/tailwind.js", CAPTURE / "tailwind.js")
    field_defs = constants("models.py", {"CHILD_FIELDS"})["CHILD_FIELDS"]
    sorts = constants("routers/children.py", {"SORT_OPTIONS", "SORT_ORDER_OPTIONS"})
    aoi = example(101, "見本家", "あおい", "さくら組", "2022-06-14")
    hinata = example(102, "見本家", "ひなた", "もも組", "2023-05-12")
    hinata.family = aoi.family
    default_fields = [f["key"] for f in field_defs if f["default"]]
    chosen_fields = ["classroom", "last_name", "first_name", "birth_date", "status"]
    labels = {f["key"]: f["label"] for f in field_defs}
    def listing(status, fields, sort_by, order, rows, annotation="", field_labels=None):
        context = dict(current_status=status, all_fields=field_defs, selected_fields=fields,
                       current_sort_by=sort_by, current_sort_order=order,
                       sort_options=sorts["SORT_OPTIONS"], sort_order_options=sorts["SORT_ORDER_OPTIONS"],
                       children=rows, total=len(rows), current_certifications={})
        if field_labels:
            context["field_labels"] = field_labels
        return offline(render("children/list.html", "/children/", **context), annotation)

    markers = """<script>
      const form = document.querySelector('#filter-form');
      for (const [i, el] of [form.querySelector('span'), form.querySelector('label[for=sort_by]'),
                             form.querySelector('label[for=sort_order]')].entries()) {
        const text = document.createElement('span');
        text.textContent = el.textContent;
        el.replaceChildren(text);
        text.dataset.guideNumber = i + 1;
        text.dataset.markerSide = 'right';
      }
    </script>"""
    fields_open = """<script>
      document.querySelector('#filter-form details').open = true;
      document.querySelector('#table-area a[href="/children/101"]').classList.add('guide-target');
    </script>"""
    detail = render("children/detail.html", "/children/101", child=aoi, can_access_observation_records=True,
                    can_view_progress_records=True, family_children=[aoi, hinata],
                    family_parent_accounts=[], guardian_profiles=[], care_mode_label="児童個別の認定を使用")
    pages = {
        "children-default": listing("enrolled", default_fields, "birth_date", "desc", [hinata, aoi]),
        "children-filters": listing("enrolled", default_fields, "birth_date", "desc", [hinata, aoi], markers),
        "children-fields": listing("enrolled", chosen_fields, "name", "asc", [aoi, hinata], fields_open, labels),
        "children-empty": listing("graduated", chosen_fields, "name", "asc", [], field_labels=labels),
        "child-detail": offline(detail, ""),
    }
    for name, html in pages.items():
        (CAPTURE / f"capture-{name}.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
