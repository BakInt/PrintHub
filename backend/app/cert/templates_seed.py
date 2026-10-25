"""证照打印内置模板数据（cert_templates 的 layout_json 唯一维护入口）。

P0 阶段 layout_json 只随代码发布：`schema.ensure_schema()` 每次启动把这里的
name/layout_json/sort 同步进库（后台只改价格与启停，不会被覆盖）。
新增证照功能的流程：在这里加一条模板数据 + 前端新增模块页 + 一行路由注册。

layout_json 约定：
- card：门户卡片元数据（icon 存 lucide 图标名字符串、theme 存主题键，前端映射视觉）；
- page_size_mm / orientation：目标纸张（P0 全部 A4 竖版）；
- slots：槽位清单，key 与前端模块页声明的槽位一一对应；
  - size_mm：目标打印尺寸（毫米）；fit="exact"（默认）= 精确缩放到该尺寸（裁剪已保证比例），
    fit="contain" = 在 size_mm 包围框内按原比例缩放居中（照片比例不定时使用）；
  - position_mm：槽位左上角在页面中的位置（毫米）；
- cut_guides：是否绘制浅灰裁剪细框；slot_labels：是否绘制槽位文字标注（P0 未使用）。

非身份证模板的目标尺寸须实物样张实测校准后才可调整上线值；当前使用保守占位值。
"""

import json

# 身份证卡 1:1 实际尺寸：85.6 × 54 mm；A4 竖版居中排布（水平居中 x=(210-85.6)/2=62.2，
# 垂直整体居中：正面 y=89.5、反面 y=153.5，两卡间距 10mm）。
ID_CARD_SLOT_SIZE_MM = [85.6, 54.0]

# 户口本：户主页 + 个人页两个槽位排入同一页 A4（与身份证正反面同页同理），
# **上下排布**与身份证一致：户主页在上（y=13.5）、个人页在下（y=153.5），
# 水平居中同列（x=(210-95)/2=57.5），各 95×130mm 包围框（比例≈105:145 实页），
# 两框间距 10mm（与身份证正反面间距一致），contain 按原比例缩放居中。
# 注意：包围框尺寸是保守占位值，正式上线前须用实物样张实测校准目标尺寸。
HUKOU_SLOT_BBOX_MM = [95.0, 130.0]
HUKOU_HOLDER_POSITION_MM = [57.5, 13.5]
HUKOU_PERSONAL_POSITION_MM = [57.5, 153.5]


def _id_card_layout() -> dict:
    return {
        "card": {"icon": "credit-card", "desc": "正反面排入一页 A4，1:1 实际尺寸", "theme": "blue"},
        "page_size_mm": [210, 297],
        "orientation": "portrait",
        "slots": [
            {"key": "front", "label": "身份证人像面", "size_mm": ID_CARD_SLOT_SIZE_MM, "position_mm": [62.2, 89.5], "rotation": 0},
            {"key": "back", "label": "身份证国徽面", "size_mm": ID_CARD_SLOT_SIZE_MM, "position_mm": [62.2, 153.5], "rotation": 0},
        ],
        "cut_guides": True,
        "slot_labels": False,
    }


def _hukou_layout() -> dict:
    return {
        "card": {"icon": "book-open", "desc": "户主页与个人页排入一页 A4", "theme": "teal"},
        "page_size_mm": [210, 297],
        "orientation": "portrait",
        "slots": [
            {"key": "holder", "label": "户口本户主页", "size_mm": HUKOU_SLOT_BBOX_MM, "position_mm": HUKOU_HOLDER_POSITION_MM, "rotation": 0, "fit": "contain"},
            {"key": "personal", "label": "户口本个人页", "size_mm": HUKOU_SLOT_BBOX_MM, "position_mm": HUKOU_PERSONAL_POSITION_MM, "rotation": 0, "fit": "contain"},
        ],
        "cut_guides": True,
        "slot_labels": False,
    }


def _doc2up_layout() -> dict:
    # doc2up（两页合一打印）不走 cert 渲染管线（无 slots/版式），在 cert_templates 里
    # 是一条「登记行」：layout_json 仅携带门户卡片元数据，使后台「证件照管理」能与其
    # 他模板完全一致地启停与设置独立单价。合成时 doc2up/service.py 会把产物登记进
    # cert_docs（status='doc2up'），独立单价经证照计价钩子按 单价×版面数×份数 生效；
    # 未设价时保持标准按页/覆盖率计价（见 cert/pricing.py 与 AGENTS 6.10）。
    return {
        "card": {"icon": "columns-2", "desc": "每两页缩排到一页 A4，自动旋转方向，支持双面", "theme": "amber"},
    }


# 内置模板清单：code 与前端模块页绑定（frontend/src/cert/modules/*.vue 的 templateCode；
# doc2up 绑定 frontend/src/doc2up/Doc2UpModule.vue）。
BUILTIN_TEMPLATES: list[dict] = [
    {
        "code": "id_card",
        "name": "身份证正反面打印",
        "sort": 10,
        "layout": _id_card_layout(),
    },
    {
        "code": "hukou",
        "name": "户口本打印",
        "sort": 20,
        "layout": _hukou_layout(),
    },
    {
        "code": "doc2up",
        "name": "两页合一打印",
        "sort": 30,
        "layout": _doc2up_layout(),
    },
]


def template_seed_rows() -> list[dict]:
    """返回可直接入库的种子行（layout 序列化为 JSON 字符串）。"""
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "sort": item["sort"],
            "layout_json": json.dumps(item["layout"], ensure_ascii=False),
        }
        for item in BUILTIN_TEMPLATES
    ]


# cert 模块自持的设置键（写入主程序 settings 表，不动 database.py 的 DEFAULT_SETTINGS）。
CERT_SETTINGS_DEFAULTS: dict[str, str] = {
    # 生成件保留时长（小时）；到期后自动清理生成件与文件记录。0 = 立即到期（仍会跳过未支付/待派发订单）。
    "cert_retention_hours": "24",
    # 每用户每日生成上限（防滥用）。0 = 不限制。
    "cert_daily_generate_limit": "20",
}
