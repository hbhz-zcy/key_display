# pyinstaller --onefile --noconsole --name "key_display" main.py
import json
import tkinter as tk
from tkinter import Canvas
from pynput import keyboard, mouse
import os
import sys
import logging

def setup_logging(log_path):
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
        ]
    )

class KeyMouseDisplay:
    def __init__(self, config_path='config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.cfg = json.load(f)

        # 配置日志
        if 'log_file' in self.cfg and self.cfg['log_file']:
            log_path = self.cfg['log_file']
            if not os.path.isabs(log_path):
                if getattr(sys, 'frozen', False):
                    base_dir = os.path.dirname(sys.executable)
                else:
                    base_dir = os.getcwd()
                log_path = os.path.join(base_dir, log_path)
        else:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.getcwd()
            log_path = os.path.join(base_dir, 'key_display.log')
        setup_logging(log_path)
        logging.info("程序启动")

        # 合并键盘和鼠标按键
        all_keys = []
        if 'keys' in self.cfg:
            for k in self.cfg['keys']:
                k.setdefault('display_name', k['name'])
                all_keys.append(k)
        if 'mouse_keys' in self.cfg:
            for k in self.cfg['mouse_keys']:
                k.setdefault('display_name', k['name'])
                all_keys.append(k)

        self.key_map = {key['name']: key for key in all_keys}

        self.pressed = set()
        self.mouse_pos = (0, 0)
        self.paused = False
        self.offset = (self.cfg['window'].get('offset_x', 0),
                       self.cfg['window'].get('offset_y', 30))
        self.base = (None, None)
        self.font_size = self.cfg.get('font_size', 12)

        self.setup_gui()
        self.start_listeners()

    def setup_gui(self):
        wcfg = self.cfg['window']
        self.root = tk.Tk()
        self.root.title(wcfg.get('title', 'Key Display'))
        self.root.geometry(f"{wcfg['width']}x{wcfg['height']}")
        self.root.resizable(False, False)
        self.root.attributes('-alpha', wcfg.get('opacity', 0.9))
        self.root.overrideredirect(True)
        # 根据配置决定是否置顶
        always_on_top = wcfg.get('always_on_top', True)
        self.root.attributes('-topmost', always_on_top)
    
        self.root.update_idletasks()
        self.base = (self.root.winfo_x(), self.root.winfo_y())

        bg_color = wcfg.get('background_color', '#1a1a1a')
        self.canvas = Canvas(self.root, width=wcfg['width'], height=wcfg['height'],
                         bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 绘制鼠标范围背景矩形
        range_cfg = self.cfg['mouse_indicator'].get('range')
        range_bg = self.cfg['mouse_indicator'].get('range_bg_color')
        if range_cfg and len(range_cfg) == 4 and range_bg:
            rx, ry, rw, rh = range_cfg
            win_w, win_h = wcfg['width'], wcfg['height']
            rx = max(0, min(rx, win_w))
            ry = max(0, min(ry, win_h))
            rw = max(0, min(rw, win_w - rx))
            rh = max(0, min(rh, win_h - ry))
            self.range_bg_rect = self.canvas.create_rectangle(
                rx, ry, rx+rw, ry+rh,
                fill=range_bg,
                outline='',
                width=0
            )
            self.canvas.tag_lower(self.range_bg_rect)
        else:
            self.range_bg_rect = None

        # 绘制按键方块
        self.rect_ids = {}
        self.text_ids = {}
        for key in self.key_map.values():
            name = key['name']
            x, y, w, h = key['rect']
            rect = self.canvas.create_rectangle(x, y, x+w, y+h,
                                                fill=key['normal_bg'],
                                                outline='', width=0)
            text = self.canvas.create_text(x+w//2, y+h//2,
                                           text=key['display_name'],
                                           fill=key['normal_fg'],
                                           font=('微软雅黑', self.font_size, 'bold'))
            self.rect_ids[name] = rect
            self.text_ids[name] = text

        # 鼠标指示圆点
        self.dot = self.canvas.create_oval(0, 0, 0, 0,
                                           fill=self.cfg['mouse_indicator']['color'],
                                           outline='')
        self.root.bind('<Alt-Button-1>', self.drag_start)
        self.root.bind('<Alt-B1-Motion>', self.drag_move)

    def drag_start(self, e):
        self.drag_xy = (e.x, e.y)

    def drag_move(self, e):
        if not self.paused:
            x = self.root.winfo_x() + e.x - self.drag_xy[0]
            y = self.root.winfo_y() + e.y - self.drag_xy[1]
            self.root.geometry(f"+{x}+{y}")
            self.base = (x, y)

    def start_listeners(self):
        keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release).start()
        mouse.Listener(on_move=self.on_mouse_move,
                       on_click=self.on_mouse_click,
                       on_scroll=self.on_mouse_scroll).start()

    def get_key_name(self, key):
        try:
            return key.char
        except AttributeError:
            return str(key).replace('Key.', '')

    def get_mouse_button_name(self, button):
        return str(button).replace('Button.', '')

    def handle_safety(self, name):
        if name == self.cfg.get('safety_key', 'f12').lower():
            self.paused = not self.paused
            always_on_top = self.cfg['window'].get('always_on_top', True)
            if self.paused:
                tx, ty = self.base[0] - self.offset[0], self.base[1] - self.offset[1]
                self.root.overrideredirect(False)
                self.root.attributes('-topmost', always_on_top)
                self.root.geometry(f"+{tx}+{ty}")
                logging.info(f"【拖动模式】窗口移至 ({tx}, {ty})")
            else:
                cx, cy = self.root.winfo_x(), self.root.winfo_y()
                self.base = (cx + self.offset[0], cy + self.offset[1])
                self.root.overrideredirect(True)
                self.root.attributes('-topmost', always_on_top)
                self.root.geometry(f"+{self.base[0]}+{self.base[1]}")
                logging.info(f"【锁定模式】窗口移至 ({self.base[0]}, {self.base[1]})")
            self.root.update()
            return True
        return False

    def on_key_press(self, key):
        name = self.get_key_name(key)
        if self.handle_safety(name):
            return
        if self.paused or name not in self.key_map:
            return
        if name not in self.pressed:
            self.pressed.add(name)
            self.root.after(0, self.update_key_ui, name, True)

    def on_key_release(self, key):
        name = self.get_key_name(key)
        if name == self.cfg.get('safety_key', 'f12').lower():
            return
        if self.paused or name not in self.key_map:
            return
        if name in self.pressed:
            self.pressed.remove(name)
            self.root.after(0, self.update_key_ui, name, False)

    def on_mouse_click(self, x, y, button, pressed):
        if self.paused:
            return
        name = self.get_mouse_button_name(button)
        if name not in ('left', 'right'):
            return
        if name not in self.key_map:
            return
        if pressed:
            if name not in self.pressed:
                self.pressed.add(name)
                self.root.after(0, self.update_key_ui, name, True)
        else:
            if name in self.pressed:
                self.pressed.remove(name)
                self.root.after(0, self.update_key_ui, name, False)

    def on_mouse_scroll(self, x, y, dx, dy):
        pass

    def update_key_ui(self, name, pressed):
        cfg = self.key_map[name]
        self.canvas.itemconfig(self.rect_ids[name],
                               fill=cfg['pressed_bg'] if pressed else cfg['normal_bg'])
        self.canvas.itemconfig(self.text_ids[name],
                               fill=cfg['pressed_fg'] if pressed else cfg['normal_fg'])

    def on_mouse_move(self, x, y):
        if self.paused:
            return
        self.mouse_pos = (x, y)
        self.root.after(0, self.update_mouse_dot)

    def update_mouse_dot(self):
        mx, my = self.mouse_pos
        win_w = self.cfg['window']['width']
        win_h = self.cfg['window']['height']

        range_cfg = self.cfg['mouse_indicator'].get('range')
        if range_cfg and len(range_cfg) == 4:
            rx, ry, rw, rh = range_cfg
            rx = max(0, min(rx, win_w))
            ry = max(0, min(ry, win_h))
            rw = max(1, min(rw, win_w - rx))
            rh = max(1, min(rh, win_h - ry))
        else:
            rx, ry, rw, rh = 0, 0, win_w, win_h

        # 读取缩放系数，默认为 1.0（即直接映射鼠标坐标）
        scale_x = self.cfg['mouse_indicator'].get('scale_x', 1.0)
        scale_y = self.cfg['mouse_indicator'].get('scale_y', 1.0)

        dx = rx + mx * scale_x
        dy = ry + my * scale_y

        # 限制在矩形内
        dx = max(rx, min(rx + rw, dx))
        dy = max(ry, min(ry + rh, dy))

        r = self.cfg['mouse_indicator']['radius']
        self.canvas.coords(self.dot, dx - r, dy - r, dx + r, dy + r)
        self.canvas.tag_raise(self.dot)

    def run(self):
        self.root.after(100, self.update_mouse_dot)
        self.root.mainloop()

if __name__ == '__main__':
    KeyMouseDisplay().run()