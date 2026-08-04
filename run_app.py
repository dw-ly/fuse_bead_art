#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_app.py — 拼豆图纸生成器启动器

启动本地服务器服务 ui/ 目录，并自动打开浏览器。
打包成 EXE:  python -m PyInstaller --onefile --noconsole --name FuseBeadArt --add-data "ui;ui" run_app.py

用法:
  python run_app.py             # 启动 + 开浏览器 + 显示控制窗口（点【退出】关闭程序）
  python run_app.py --no-browser # 不自动开浏览器
  python run_app.py --test      # 只启动服务器并打印 URL 到 stdout（自动化测试用）
"""
import functools
import http.server
import os
import sys
import threading
import webbrowser


def resource_path(rel):
    """开发期取项目目录；打包后取 PyInstaller 解包目录。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 不打印每请求日志


def start_server(ui_dir, port=0):
    handler = functools.partial(QuietHandler, directory=ui_dir)
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)


def _log_error(msg):
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pindou_error.log')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def _show_error(msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror('拼豆图纸生成器', msg)
        r.destroy()
    except Exception:
        pass


def show_control(url, httpd):
    """小控制窗口：提示已启动，提供【退出】按钮（GUI 版关闭服务器的唯一途径）。"""
    import tkinter as tk
    root = tk.Tk()
    root.title('拼豆图纸生成器')
    root.resizable(False, False)
    tk.Label(root, text='✅ 已在浏览器中打开', font=('Microsoft YaHei', 11)).pack(pady=(14, 2))
    tk.Label(root, text=url, fg='#777', font=('Consolas', 9)).pack(pady=(0, 6))
    tk.Label(root, text='使用完成后点击下方按钮退出程序', fg='#999', font=('Microsoft YaHei', 9)).pack()
    tk.Button(root, text='退　出', width=14, font=('Microsoft YaHei', 10),
              command=root.destroy).pack(pady=(10, 14))
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.mainloop()
    httpd.shutdown()


def main():
    ui_dir = resource_path('ui')
    if not os.path.isdir(ui_dir):
        msg = f'未找到 ui 目录：{ui_dir}\n请确认 exe 与 ui 文件夹在同一目录（或重新打包）。'
        print(msg)
        _log_error(msg)
        _show_error(msg)
        return 1

    test_mode = '--test' in sys.argv
    try:
        httpd = start_server(ui_dir, port=(18123 if test_mode else 0))
    except OSError as e:
        # 固定端口被占 → 测试模式退回随机端口
        if test_mode:
            httpd = start_server(ui_dir, 0)
        else:
            msg = f'启动本地服务器失败：{e}'
            print(msg)
            _log_error(msg)
            _show_error(msg)
            return 1
    except Exception as e:
        msg = f'启动本地服务器失败：{e}'
        print(msg)
        _log_error(msg)
        _show_error(msg)
        return 1

    port = httpd.server_address[1]
    url = f'http://127.0.0.1:{port}/pindou.html'
    print(f'Pindou UI: {url}')
    if test_mode:
        # 测试模式：写 URL 到文件（noconsole 版 exe 无 stdout），不开浏览器不弹窗
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pindou_test_url.txt'), 'w', encoding='utf-8') as f:
                f.write(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        httpd.shutdown()
        return 0

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    if '--no-browser' not in sys.argv:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        show_control(url, httpd)
    except Exception:
        # 无 GUI 环境则退化为阻塞运行（Ctrl+C 退出）
        try:
            while True:
                import time
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        httpd.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
