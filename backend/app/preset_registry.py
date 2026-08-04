"""科研绘图预设注册表。

第三方仓库只作为本地可选资源，不提交到主仓库。每个预设都有内置
兜底样式，因此全新克隆项目时也能正常生成图片。
"""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRESETS_ROOT = PROJECT_ROOT / "presets"


class PresetError(ValueError):
    """预设 ID 不存在。"""


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    source: str
    source_url: str
    category: str
    styles: tuple[str, ...]
    fallback: str
    repo_key: str | None = None


PRESETS: tuple[Preset, ...] = (
    Preset(
        id="default",
        name="默认",
        description="Matplotlib 默认风格，适合快速预览。",
        source="内置",
        source_url="",
        category="基础",
        styles=(),
        fallback="default",
    ),
    Preset(
        id="science",
        name="SciencePlots 科研",
        description="简洁、细线、内向刻度，适合一般科研论文。",
        source="garrettj403/SciencePlots",
        source_url="https://github.com/garrettj403/SciencePlots",
        category="论文",
        styles=("science", "no-latex"),
        fallback="science",
        repo_key="scienceplots",
    ),
    Preset(
        id="science-nature",
        name="Nature 期刊",
        description="Nature 论文常用的紧凑无衬线风格。",
        source="garrettj403/SciencePlots",
        source_url="https://github.com/garrettj403/SciencePlots",
        category="期刊",
        styles=("science", "nature", "no-latex"),
        fallback="nature",
        repo_key="scienceplots",
    ),
    Preset(
        id="science-ieee",
        name="IEEE 期刊",
        description="适合 IEEE 单栏论文的紧凑黑白友好风格。",
        source="garrettj403/SciencePlots",
        source_url="https://github.com/garrettj403/SciencePlots",
        category="期刊",
        styles=("science", "ieee", "no-latex"),
        fallback="ieee",
        repo_key="scienceplots",
    ),
    Preset(
        id="science-bright",
        name="SciencePlots 色盲友好",
        description="使用 SciencePlots bright 色循环，适合多系列数据。",
        source="garrettj403/SciencePlots",
        source_url="https://github.com/garrettj403/SciencePlots",
        category="配色",
        styles=("science", "bright", "no-latex"),
        fallback="science",
        repo_key="scienceplots",
    ),
    Preset(
        id="lovely",
        name="LovelyPlots 论文",
        description="干净、可编辑，适合论文和学位论文排版。",
        source="killiansheriff/LovelyPlots",
        source_url="https://github.com/killiansheriff/LovelyPlots",
        category="论文",
        styles=(),
        fallback="lovely",
        repo_key="lovelyplots",
    ),
    Preset(
        id="tueplots",
        name="期刊尺寸（tueplots）",
        description="按出版物尺寸和字体层级组织的基础风格。",
        source="pnkraemer/tueplots",
        source_url="https://github.com/pnkraemer/tueplots",
        category="尺寸",
        styles=(),
        fallback="tueplots",
        repo_key="tueplots",
    ),
)

_PRESETS_BY_ID = {preset.id: preset for preset in PRESETS}


def get_preset(preset_id: str | None) -> Preset:
    key = (preset_id or "default").strip() or "default"
    try:
        return _PRESETS_BY_ID[key]
    except KeyError as exc:
        raise PresetError(f"未知预设: {key}") from exc


def _repo_path(repo_key: str) -> Path:
    return {
        "scienceplots": PRESETS_ROOT / "SciencePlots" / "src" / "scienceplots",
        "lovelyplots": PRESETS_ROOT / "LovelyPlots" / "lovelyplots",
        "tueplots": PRESETS_ROOT / "tueplots" / "tueplots",
    }[repo_key]


def local_available(preset: Preset) -> bool:
    return bool(preset.repo_key and _repo_path(preset.repo_key).is_dir())


def list_presets() -> list[dict]:
    """返回前端可展示的预设信息，不暴露本地路径。"""
    return [
        {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "source": preset.source,
            "source_url": preset.source_url,
            "category": preset.category,
            "local_available": local_available(preset),
            "has_fallback": preset.fallback != "default" or preset.id == "default",
        }
        for preset in PRESETS
    ]


def runtime_options(preset_id: str | None) -> dict:
    """返回沙箱需要的静态运行参数。"""
    preset = get_preset(preset_id)
    scienceplots_src = None
    if preset.repo_key == "scienceplots" and local_available(preset):
        scienceplots_src = str(PRESETS_ROOT / "SciencePlots" / "src")
    return {
        "id": preset.id,
        "styles": list(preset.styles),
        "fallback": preset.fallback,
        "scienceplots_src": scienceplots_src,
    }
