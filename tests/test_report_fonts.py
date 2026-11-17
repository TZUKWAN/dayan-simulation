"""Portable CJK rendering uses the bundled OFL font, without system font assumptions."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan import fonts


class ReportFonts(unittest.TestCase):
    def test_packaged_font_renders_chinese_and_unicode_minus_without_missing_glyphs(self):
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib import pyplot as plt
        with tempfile.TemporaryDirectory() as td,warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always');family=fonts.configure_matplotlib()
            self.assertEqual(family,'Noto Sans CJK SC')
            fig,ax=plt.subplots();ax.plot([-1,0,1],[3,2,4]);ax.set_title('大衍研究报告：真实数据、模型校准与独立留出验证')
            ax.set_xlabel('仿真时间');ax.set_ylabel('主体状态变化 −1')
            path=Path(td)/'chinese-report.png';fig.savefig(path,dpi=100);plt.close(fig)
            self.assertGreater(path.stat().st_size,1000)
            self.assertFalse([w for w in caught if 'Glyph' in str(w.message) and 'missing' in str(w.message)])
            self.assertIn('SIL OPEN FONT LICENSE',(fonts.FONT_PATH.parent/'OFL.txt').read_text(encoding='utf-8'))

    def test_missing_font_is_an_explicit_deployment_failure(self):
        fonts.font_family.cache_clear()
        try:
            with patch.object(fonts,'FONT_PATH',Path('unit-missing-font.otf')):
                with self.assertRaisesRegex(RuntimeError,'缺少'):fonts.font_family()
        finally:fonts.font_family.cache_clear()


if __name__=='__main__':unittest.main(verbosity=2)
