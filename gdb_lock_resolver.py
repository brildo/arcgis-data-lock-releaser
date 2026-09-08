# -*- coding: utf-8 -*-
"""
ArcGIS Pro 地理数据 (GDB / Shapefile) 独占锁解除小工具
GUI 主界面程序 (gdb_lock_resolver.py)
"""

import os
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import handle_closer
import lock_engine


class GDBLockResolverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ArcGIS Pro 数据独占锁解除工具 (GDB / Shapefile) v1.1")
        self.root.geometry("980x680")
        self.root.minsize(840, 560)

        # 设置高 DPI 缩放适配
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.is_admin = handle_closer.is_admin()
        self.scanning = False
        self.auto_refresh = tk.BooleanVar(value=False)
        self.auto_refresh_thread = None

        # 缓存扫描结果
        self.current_records = []

        self._setup_style()
        self._build_ui()

        # 启动后执行初始检测
        self.log("工具启动完成。正在检测系统环境...")
        if not self.is_admin:
            self.log("[警告] 当前未以管理员身份运行！建议点击上方【提权重启程序】以获得完整跨进程句柄操作权限。")
        else:
            self.log("[就绪] 当前已具备管理员权限。")

        self.root.after(200, self.refresh_data)

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        # 调优颜色
        bg_main = "#f5f6f8"
        self.root.configure(bg=bg_main)

        style.configure("Main.TFrame", background=bg_main)
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 12, "bold"), background=bg_main, foreground="#1f2937")
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9), background=bg_main, foreground="#6b7280")
        style.configure("Stat.TLabel", font=("Microsoft YaHei UI", 10), background="#ffffff", foreground="#374151")

        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=6, background="#2563eb", foreground="#ffffff")
        style.map("Primary.TButton", background=[("active", "#1d4ed8")])

        style.configure("Danger.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=6, background="#dc2626", foreground="#ffffff")
        style.map("Danger.TButton", background=[("active", "#b91c1c")])

        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#e5e7eb", foreground="#374151")
        style.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=28)

    def _build_ui(self):
        # 顶部卡片：状态与权限提示
        top_frame = ttk.Frame(self.root, style="Main.TFrame", padding=(16, 12, 16, 8))
        top_frame.pack(fill=tk.X)

        title_lbl = ttk.Label(top_frame, text="ArcGIS Pro 地理数据独占锁解除管理器", style="Header.TLabel")
        title_lbl.pack(anchor=tk.W)

        sub_lbl = ttk.Label(
            top_frame,
            text="无需关闭 ArcGIS Pro，精准识别并安全释放 File GDB 及 Shapefile 的 Windows 文件句柄与独占锁",
            style="Sub.TLabel"
        )
        sub_lbl.pack(anchor=tk.W, pady=(2, 8))

        # 状态条
        status_bar = ttk.Frame(top_frame, style="Card.TFrame", padding=10)
        status_bar.pack(fill=tk.X)

        self.admin_badge = tk.Label(
            status_bar,
            text="管理员: 是" if self.is_admin else "管理员: 否 (受限)",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#dcfce7" if self.is_admin else "#fee2e2",
            fg="#15803d" if self.is_admin else "#b91c1c",
            padx=8, pady=2
        )
        self.admin_badge.pack(side=tk.LEFT, padx=(0, 10))

        if not self.is_admin:
            btn_restart_admin = tk.Button(
                status_bar,
                text="提权重启程序",
                font=("Microsoft YaHei UI", 9, "underline"),
                fg="#b91c1c", bg="#ffffff", bd=0, cursor="hand2",
                command=self.restart_as_admin
            )
            btn_restart_admin.pack(side=tk.LEFT, padx=(0, 15))

        self.proc_status_lbl = ttk.Label(status_bar, text="正在检测 ArcGIS 进程...", style="Stat.TLabel")
        self.proc_status_lbl.pack(side=tk.LEFT, padx=5)

        # 自动刷新开关
        auto_chk = ttk.Checkbutton(
            status_bar,
            text="自动巡检 (每5秒)",
            variable=self.auto_refresh,
            command=self._toggle_auto_refresh
        )
        auto_chk.pack(side=tk.RIGHT, padx=5)

        # 中部主体：表格与操作按钮
        body_frame = ttk.Frame(self.root, style="Main.TFrame", padding=(16, 0, 16, 8))
        body_frame.pack(fill=tk.BOTH, expand=True)

        # 工具栏
        toolbar = ttk.Frame(body_frame, style="Main.TFrame")
        toolbar.pack(fill=tk.X, pady=(4, 8))

        btn_refresh = ttk.Button(toolbar, text=" 重新扫描占用 ", style="Primary.TButton", command=self.refresh_data)
        btn_refresh.pack(side=tk.LEFT, padx=(0, 8))

        btn_release_sel = ttk.Button(toolbar, text=" 释放选中数据锁 ", style="Danger.TButton", command=self.release_selected)
        btn_release_sel.pack(side=tk.LEFT, padx=(0, 8))

        btn_release_all = ttk.Button(toolbar, text=" 一键释放全部锁 ", style="Danger.TButton", command=self.release_all)
        btn_release_all.pack(side=tk.LEFT, padx=(0, 8))

        btn_verify = ttk.Button(toolbar, text=" 验证选中数据读写 ", command=self.verify_selected)
        btn_verify.pack(side=tk.LEFT, padx=(0, 8))

        btn_open_folder = ttk.Button(toolbar, text=" 打开所在文件夹 ", command=self.open_selected_folder)
        btn_open_folder.pack(side=tk.LEFT)

        # 列表容器
        table_frame = ttk.Frame(body_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("dataset_path", "dataset_type", "proc_name", "pid", "handles_count", "locks_count", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("dataset_path", text="地理数据路径 / 名称")
        self.tree.heading("dataset_type", text="数据类型")
        self.tree.heading("proc_name", text="占用进程")
        self.tree.heading("pid", text="PID")
        self.tree.heading("handles_count", text="文件句柄数")
        self.tree.heading("locks_count", text=".lock 锁文件")
        self.tree.heading("status", text="当前状态")

        self.tree.column("dataset_path", width=360, anchor=tk.W)
        self.tree.column("dataset_type", width=95, anchor=tk.CENTER)
        self.tree.column("proc_name", width=110, anchor=tk.CENTER)
        self.tree.column("pid", width=65, anchor=tk.CENTER)
        self.tree.column("handles_count", width=80, anchor=tk.CENTER)
        self.tree.column("locks_count", width=85, anchor=tk.CENTER)
        self.tree.column("status", width=95, anchor=tk.CENTER)

        tree_scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        # 详细信息与日志区域
        bottom_frame = ttk.Frame(self.root, style="Main.TFrame", padding=(16, 0, 16, 12))
        bottom_frame.pack(fill=tk.BOTH)

        log_lbl = ttk.Label(bottom_frame, text="操作日志与详情", style="Header.TLabel")
        log_lbl.pack(anchor=tk.W, pady=(4, 2))

        self.log_text = tk.Text(
            bottom_frame,
            height=7,
            font=("Consolas", 9),
            bg="#1e293b",
            fg="#e2e8f0",
            insertbackground="#ffffff",
            relief="flat",
            wrap=tk.WORD
        )
        log_scroll = ttk.Scrollbar(bottom_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def refresh_data(self):
        if self.scanning:
            return
        self.scanning = True

        def run_scan():
            try:
                procs = lock_engine.get_arcgis_processes()
                proc_str = f"发现 {len(procs)} 个 ArcGIS 进程" if procs else "未发现运行中的 ArcGIS 进程"
                if procs:
                    proc_details = ", ".join([f"{p['name']}({p['pid']})" for p in procs])
                    proc_str += f": {proc_details}"

                records = lock_engine.scan_all_arcgis_locks()

                self.root.after(0, lambda: self._update_ui_results(procs, proc_str, records))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"[错误] 扫描过程异常: {e}"))
            finally:
                self.scanning = False

        threading.Thread(target=run_scan, daemon=True).start()

    def _update_ui_results(self, procs, proc_str, records):
        self.proc_status_lbl.config(text=proc_str)
        self.current_records = records

        # 清空已有行
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not records:
            if procs:
                self.log("已完成扫描：ArcGIS 正在运行，但未检测到对任何 GDB 或 Shapefile 的锁定句柄。")
            else:
                self.log("已完成扫描：未发现 ArcGIS 进程。")
        else:
            self.log(f"扫描完成：共检测到 {len(records)} 处地理数据占用记录。")

        for idx, rec in enumerate(records):
            status = "已占用锁定"
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    rec['dataset_path'],
                    rec['dataset_type'],
                    rec['process_name'],
                    rec['pid'],
                    len(rec['handles']),
                    len(rec['lock_files']),
                    status
                )
            )

    def _toggle_auto_refresh(self):
        if self.auto_refresh.get():
            self.log("已开启自动巡检（每5秒）")
            self._schedule_auto_refresh()
        else:
            self.log("已关闭自动巡检")

    def _schedule_auto_refresh(self):
        if self.auto_refresh.get():
            self.refresh_data()
            self.root.after(5000, self._schedule_auto_refresh)

    def get_selected_records(self):
        selected_iids = self.tree.selection()
        if not selected_iids:
            return []
        records = []
        for iid in selected_iids:
            try:
                idx = int(iid)
                if 0 <= idx < len(self.current_records):
                    records.append(self.current_records[idx])
            except Exception:
                pass
        return records

    def release_selected(self):
        records = self.get_selected_records()
        if not records:
            messagebox.showinfo("提示", "请先在列表中选中需要释放锁的数据项。")
            return

        confirm = messagebox.askyesno(
            "安全确认",
            f"确定要释放选中的 {len(records)} 个地理数据集独占锁吗？\n\n"
            "建议确保：\n"
            "1. 用户已在 ArcGIS Pro 中移除了该图层或处于非编辑状态；\n"
            "2. 本操作将强制断开 Pro 对该文件的底层文件句柄并清理锁文件。\n\n"
            "是否继续？"
        )
        if not confirm:
            return

        self._do_release(records)

    def release_all(self):
        if not self.current_records:
            messagebox.showinfo("提示", "当前无检测到的数据占用。")
            return

        confirm = messagebox.askyesno(
            "安全确认",
            f"确定要释放当前检测到的全部 {len(self.current_records)} 个数据独占锁吗？\n\n"
            "是否继续？"
        )
        if not confirm:
            return

        self._do_release(self.current_records)

    def _do_release(self, records):
        def task():
            for rec in records:
                dpath = rec['dataset_path']
                dtype = rec['dataset_type']
                pid = rec['pid']
                handles = rec['handles']
                self.root.after(0, lambda p=dpath, t=dtype: self.log(f"正在解除 {t} [{os.path.basename(p)}] 独占锁 (PID={pid})..."))

                success, desc = lock_engine.release_dataset_lock(pid, dtype, dpath, handles)
                self.root.after(0, lambda p=dpath, s=success, d=desc: self._on_release_done(p, s, d))

            self.root.after(500, self.refresh_data)

        threading.Thread(target=task, daemon=True).start()

    def _on_release_done(self, dpath, success, desc):
        status_str = "【成功释放】" if success else "【部分释放/受限】"
        self.log(f"{status_str} {dpath}\n{desc}")

    def verify_selected(self):
        records = self.get_selected_records()
        if not records:
            messagebox.showinfo("提示", "请选择需要验证的数据项。")
            return

        for rec in records:
            dpath = rec['dataset_path']
            dtype = rec['dataset_type']
            ok, msg = lock_engine.verify_dataset_writable(dtype, dpath)
            res = "正常 (可写)" if ok else "受阻 (仍有占用)"
            self.log(f"验证结果 [{os.path.basename(dpath)}]: {res} -> {msg}")
            messagebox.showinfo("验证结果", f"数据: {dpath}\n类型: {dtype}\n状态: {res}\n详情: {msg}")

    def open_selected_folder(self):
        records = self.get_selected_records()
        if not records:
            messagebox.showinfo("提示", "请选择需要打开的数据项。")
            return
        dpath = records[0]['dataset_path']
        target = dpath
        if not os.path.exists(target):
            target = os.path.dirname(dpath)

        if os.path.exists(target):
            subprocess.Popen(f'explorer /select,"{os.path.abspath(target)}"')
        else:
            messagebox.showwarning("警告", "目标文件或目录不存在。")

    def restart_as_admin(self):
        """通过 PowerShell 提升管理员权限重新启动当前脚本（无 CMD 黑框）"""
        try:
            script_path = os.path.abspath(__file__)
            py_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(py_dir, "pythonw.exe")
            py_exe = pythonw if os.path.exists(pythonw) else sys.executable
            cmd = f'Start-Process "{py_exe}" -ArgumentList "\'{script_path}\'" -Verb RunAs -WindowStyle Hidden'
            subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", cmd])
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("提权失败", f"无法以管理员身份启动: {e}")


def main():
    root = tk.Tk()
    app = GDBLockResolverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
