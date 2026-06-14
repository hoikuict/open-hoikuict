# -*- coding: utf-8 -*-
"""
open-hoikuict 向け SQLModel 定義。
generate.py が出力する bunrei テーブルにマップする。

実運用での主クエリは「年齢×季節(月)×記入項目」での候補絞り込み:
    select(Bunrei).where(
        Bunrei.plan_type == "月案",
        Bunrei.age_class == "1歳児",
        Bunrei.month == 1,
        Bunrei.item == "教育のねらい",
    )
領域でさらに絞るなら .where(Bunrei.ryoiki == "健康") を追加。
"""
from typing import Optional
from sqlmodel import SQLModel, Field


class Bunrei(SQLModel, table=True):
    __tablename__ = "bunrei"

    id: str = Field(primary_key=True, max_length=12)

    # ---- 分類軸（フィルタキー）----
    plan_type: str = Field(index=True, description="計画種別: 年案/月案/週案/個人案")
    age_class: str = Field(index=True, description="クラス: 0歳児..5歳児")
    age_detail: Optional[str] = Field(default=None, description="個人案の月齢刻み、またはクラス")
    dev_band: Optional[str] = Field(default=None, description="指針の発達区分: nyuuji/1to3/over3")
    time_unit: Optional[str] = Field(default=None, description="月(4..3) または 期(Ⅰ..Ⅳ)")
    month: Optional[int] = Field(default=None, index=True, description="代表月。季節フィルタ用")
    item: str = Field(index=True, description="記入項目: ねらい/活動内容/環境構成・援助 等")
    ryoiki: Optional[str] = Field(default=None, index=True,
                                  description="5領域/乳児3視点/養護。一般項目はNull")
    direction: Optional[str] = Field(default=None, description="ねらいの方向性（指針由来）")
    juu_no_sugata: Optional[str] = Field(default=None, index=True,
                                         description="10の姿。3歳以上の付加軸")

    # ---- 本文 ----
    text: str = Field(description="文例本文")

    # ---- 出所・監修フラグ ----
    text_provenance: str = Field(default="ai_generated",
                                 description="文面の出所: ai_generated/facility/curated")
    framework_source: str = Field(default="shishin_framework",
                                  description="分類枠組みの出所。指針告示由来")
    needs_review: bool = Field(default=True,
                               description="保育士監修が未了かどうか。Trueは本番非推奨")


class BunreiFacility(SQLModel, table=True):
    __tablename__ = "bunrei_facility"

    id: str = Field(primary_key=True, max_length=14)
    nursery_ref: str = Field(index=True, description="園スコープ")
    visibility: str = Field(default="facility_private", description="園内限定")
    plan_type: Optional[str] = Field(default=None, index=True)
    age_class: Optional[str] = Field(default=None, index=True)
    month: Optional[int] = Field(default=None, index=True)
    item: Optional[str] = Field(default=None, index=True)
    ryoiki: Optional[str] = Field(default=None, index=True)
    text: str = Field(description="園文例本文")
    text_provenance: str = Field(default="facility")
    masked: bool = Field(default=False, description="自動マスクが入ったか")
    needs_review: bool = Field(default=True, description="園内確認が必要")
    source_note: Optional[str] = Field(default=None)
    imported_at: str
