"""Private profile images, normalized before transactional database storage."""
from dataclasses import dataclass
from io import BytesIO
import warnings

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlmodel import Session

from models import ProfilePhoto

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000


def normalize_photo(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    content = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("写真は1枚10MB以内にしてください。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("写真はJPEG・PNG・WebP形式で選択してください。")
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("写真は2500万画素以内にしてください。")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((1024, 1024))
                # Rebuild pixels on a clean image to discard EXIF/GPS and metadata.
                rgba = oriented.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                result = BytesIO()
                clean.save(result, format="JPEG", quality=85, optimize=True)
                return result.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("写真を読み込めません。JPEG・PNG・WebP形式の画像を選択してください。") from exc


@dataclass
class PhotoUploads:
    files: dict[str, UploadFile | None]
    removals: dict[str, bool]

    def validate(self) -> dict[str, bytes | None]:
        edits = {}
        for key, upload in self.files.items():
            if self.removals[key] and upload and upload.filename:
                raise ValueError("写真の差し替えと削除は同時に指定できません。")
            data = normalize_photo(upload)
            if data is not None or self.removals[key]:
                edits[key] = data
        return edits


def photo_uploads(
    child_photo: UploadFile | None = File(None),
    g1_photo: UploadFile | None = File(None),
    g2_photo: UploadFile | None = File(None),
    child_photo_remove: bool = Form(False),
    g1_photo_remove: bool = Form(False),
    g2_photo_remove: bool = Form(False),
) -> PhotoUploads:
    return PhotoUploads(
        {"child": child_photo, "g1": g1_photo, "g2": g2_photo},
        {"child": child_photo_remove, "g1": g1_photo_remove, "g2": g2_photo_remove},
    )


def save_photo(session: Session, content: bytes | None, *, child_id=None, family_id=None) -> str | None:
    if content is None:
        return None
    photo = ProfilePhoto(content=content, child_id=child_id, family_id=family_id)
    session.add(photo)
    session.flush()
    return photo.id


def edit_guardian_photos(session: Session, profiles: list[dict], edits: dict, *, family_id: int) -> list[dict]:
    profiles = [dict(profile) for profile in profiles]
    for order in (1, 2):
        key = f"g{order}"
        if key not in edits:
            continue
        profile = next((p for p in profiles if p["order"] == order), None)
        if profile is None:
            raise HTTPException(400, f"保護者{order}の写真を登録するには、姓と名を入力してください。")
        profile["photo_id"] = save_photo(session, edits[key], family_id=family_id)
    return profiles


def apply_family_photo_edits(session: Session, family, edits: dict, *, actor_name: str | None = None) -> None:
    from family_support import set_family_guardian_profiles
    from child_profile_history import build_child_profile_snapshot, record_child_profile_history
    from models import Child, Guardian
    from sqlmodel import select

    if not any(key in edits for key in ("g1", "g2")):
        return
    children = session.exec(select(Child).where(Child.family_id == family.id)).all()
    previous = [(child, build_child_profile_snapshot(session, child)) for child in children] if actor_name else []

    profiles = edit_guardian_photos(session, family.guardian_profiles(), edits, family_id=family.id)
    set_family_guardian_profiles(family, profiles)
    session.add(family)
    by_order = {profile["order"]: profile.get("photo_id") for profile in profiles}
    # The family JSON is canonical; keep legacy per-child guardians in sync.
    child_ids = [child.id for child in children]
    for guardian in session.exec(select(Guardian).where(Guardian.child_id.in_(child_ids))).all():
        guardian.photo_id = by_order.get(guardian.order)
        session.add(guardian)
    for child, snapshot in previous:
        record_child_profile_history(session, child, actor_name=actor_name, previous_snapshot=snapshot)


def photo_response(session: Session, photo_id: str) -> Response:
    photo = session.get(ProfilePhoto, photo_id)
    if photo is None:
        raise HTTPException(404, "写真が見つかりません")
    return Response(photo.content, media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })
