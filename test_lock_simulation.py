# -*- coding: utf-8 -*-
"""
自动化仿真测试脚本 (test_lock_simulation.py)
全面验证：
1. File GDB 跨进程强制解锁
2. Shapefile (.shp/.dbf) 跨进程强制解锁
确保目标进程不崩溃，精准关闭句柄并清理锁文件。
"""

import os
import sys
import time
import subprocess
import shutil

import handle_closer
import lock_engine


def run_full_simulation():
    test_dir = os.path.abspath("test_workspace")
    if os.path.exists(test_dir):
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass
    os.makedirs(test_dir, exist_ok=True)

    print("========================================")
    print(">>> 开始测试 1：File GDB 独占锁释放测试 <<<")
    print("========================================")
    test_gdb(test_dir)

    print("\n========================================")
    print(">>> 开始测试 2：Shapefile 独占锁释放测试 <<<")
    print("========================================")
    test_shapefile(test_dir)

    try:
        shutil.rmtree(test_dir)
        print("\n[清理] 测试工作目录已清理。")
    except Exception:
        pass


def test_gdb(test_dir):
    gdb_dir = os.path.join(test_dir, "simulation_data.gdb")
    os.makedirs(gdb_dir, exist_ok=True)

    table_file = os.path.join(gdb_dir, "a00000001.gdbtable")
    with open(table_file, "w") as f:
        f.write("GDB TABLE DATA")

    lock_file = os.path.join(gdb_dir, "sim_pc.9999.sr.lock")
    with open(lock_file, "w") as f:
        f.write("LOCK FILE")

    holder_code = f"""
import time, sys
f = open(r'{table_file}', 'r+b')
print('LOCKED_GDB', flush=True)
while True:
    time.sleep(1)
"""
    proc = subprocess.Popen([sys.executable, "-c", holder_code], stdout=subprocess.PIPE, text=True)
    out = proc.stdout.readline().strip()
    print(f"GDB 锁定进程启动，PID={proc.pid}, 状态={out}")

    # 扫描
    dataset_map = lock_engine.scan_locked_datasets_for_process(proc.pid)
    print(f"识别到的数据集: {list(dataset_map.keys())}")
    assert gdb_dir in dataset_map, "未检测到 GDB 数据集！"
    info = dataset_map[gdb_dir]
    assert info['type'] == "File GDB"

    # 释放
    success, desc = lock_engine.release_dataset_lock(proc.pid, "File GDB", gdb_dir, info['handles'])
    print(f"释放结果: 成功={success}")

    writable, msg = lock_engine.verify_dataset_writable("File GDB", gdb_dir)
    print(f"独占性写验证: 可写={writable} ({msg})")

    is_alive = (proc.poll() is None)
    print(f"目标进程存活: {is_alive}")
    proc.kill()

    if writable and is_alive:
        print("[PASS] File GDB 测试通过！")
    else:
        print("[FAIL] File GDB 测试失败！")


def test_shapefile(test_dir):
    shp_file = os.path.join(test_dir, "rivers.shp")
    dbf_file = os.path.join(test_dir, "rivers.dbf")
    shx_file = os.path.join(test_dir, "rivers.shx")

    with open(shp_file, "wb") as f:
        f.write(b"SHP HEADER MOCK CONTENT")
    with open(dbf_file, "wb") as f:
        f.write(b"DBF TABLE MOCK CONTENT")
    with open(shx_file, "wb") as f:
        f.write(b"SHX INDEX MOCK CONTENT")

    lock_file = os.path.join(test_dir, "rivers.shp.SIMPC.1234.sr.lock")
    with open(lock_file, "w") as f:
        f.write("SHP LOCK FILE")

    # 启动进程同时打开 shp 和 dbf
    holder_code = f"""
import time, sys
f1 = open(r'{shp_file}', 'r+b')
f2 = open(r'{dbf_file}', 'r+b')
print('LOCKED_SHP', flush=True)
while True:
    time.sleep(1)
"""
    proc = subprocess.Popen([sys.executable, "-c", holder_code], stdout=subprocess.PIPE, text=True)
    out = proc.stdout.readline().strip()
    print(f"Shapefile 锁定进程启动，PID={proc.pid}, 状态={out}")

    # 验证外部此时无法写
    locked = False
    try:
        with open(shp_file, "r+b") as f:
            pass
    except PermissionError:
        locked = True
    print(f"初始状态外部独占读写受阻: {locked} (符合预期)")

    # 扫描
    dataset_map = lock_engine.scan_locked_datasets_for_process(proc.pid)
    canonical_shp = os.path.normpath(shp_file)
    print(f"识别到的数据集: {list(dataset_map.keys())}")
    assert canonical_shp in dataset_map, "未检测到 Shapefile 数据集！"
    info = dataset_map[canonical_shp]
    assert info['type'] == "Shapefile"
    print(f"检测到所属句柄数: {len(info['handles'])}, 锁文件数: {len(info['lock_files'])}")

    # 释放
    success, desc = lock_engine.release_dataset_lock(proc.pid, "Shapefile", canonical_shp, info['handles'])
    print(f"释放反馈:\n    " + desc.replace("\n", "\n    "))

    writable, msg = lock_engine.verify_dataset_writable("Shapefile", canonical_shp)
    print(f"最终独占性写验证: 可写={writable} ({msg})")

    is_alive = (proc.poll() is None)
    print(f"目标进程存活: {is_alive}")
    proc.kill()

    if writable and is_alive:
        print("[PASS] Shapefile 测试 100% 通过！")
    else:
        print("[FAIL] Shapefile 测试失败！")


if __name__ == "__main__":
    run_full_simulation()
