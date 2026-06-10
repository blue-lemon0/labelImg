import math
from PyQt5.QtCore import QElapsedTimer


class KeyAccelerator:
    """方向键移动的指数加速器。
    
    factor = 1 + max_accel * (1 - e^(-elapsed / time_constant))
    step = max(1, round(base_step * factor))
    
    用法:
        accel = KeyAccelerator(max_accel=4.0, time_constant=0.3)
        accel.start()           # 首次按键时
        step = accel.step()     # 每次定时器 tick → 像素步长
        accel.stop()            # 所有键松开时
    """

    def __init__(self, max_accel=4.0, time_constant=0.3, base_step=1.0):
        self.max_accel = max_accel          # 最高速度倍率
        self.time_constant = time_constant  # 时间常数 τ，越大加速越慢
        self.base_step = base_step          # 基础步长（最慢时每 tick 像素）
        self._timer = QElapsedTimer()
        self._running = False
        self._last_logged_step = 0

    def start(self):
        """开始计时（首次按下方向键时调用）。"""
        self._timer.start()
        self._running = True
        self._last_logged_step = 0

    def stop(self):
        """重置加速状态（所有方向键松开时调用）。"""
        self._running = False
        self._last_logged_step = 0

    def step(self):
        """返回当前加速后的每 tick 像素步长。"""
        if not self._running:
            return int(round(self.base_step))
        elapsed = self._timer.elapsed() / 1000.0  # ms → 秒
        factor = 1.0 + self.max_accel * (1.0 - math.exp(-elapsed / self.time_constant))
        step = max(1, int(round(self.base_step * factor)))
        if step != self._last_logged_step:
            self._last_logged_step = step
        return step
