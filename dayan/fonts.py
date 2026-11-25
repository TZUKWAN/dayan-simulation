"""A bundled, licensed CJK font; missing assets are explicit deployment errors."""
from functools import lru_cache
from pathlib import Path

FONT_PATH=Path(__file__).resolve().parents[1]/'assets/fonts/NotoSansCJKsc-Regular.otf'


@lru_cache(maxsize=1)
def font_family():
    from matplotlib import font_manager
    if not FONT_PATH.is_file():raise RuntimeError('缺少随应用分发的中文字体：'+str(FONT_PATH))
    import hashlib
    if hashlib.sha256(FONT_PATH.read_bytes()).hexdigest()!='2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b':
        raise RuntimeError('随应用分发的中文字体哈希不匹配')
    font_manager.fontManager.addfont(str(FONT_PATH))
    family=font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
    from matplotlib.ft2font import FT2Font
    supported=FT2Font(str(FONT_PATH)).get_charmap()
    required=set('大衍研究报告模型时间主体状态真实数据独立留出验证干预变化分析仿真校准平均值−')
    missing=[char for char in required if ord(char) not in supported]
    if missing:raise RuntimeError('中文字体缺少必要字形：'+''.join(missing))
    return family


def configure_matplotlib():
    import matplotlib
    matplotlib.rcParams['font.sans-serif']=[font_family(),'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus']=True
    return font_family()
