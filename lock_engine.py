# -*- coding: utf-8 -*-
"""
核心锁检测与解除业务逻辑 (lock_engine.py)
全面支持 File Geodatabase (.gdb) 与 Shapefile (.shp) 的独占锁识别与释放
"""

import os
import glob
import logging
import subprocess
import shutil
import ctypes
from ctypes import wintypes
import handle_closer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LockEngine")

# Shapefile 常见的关联扩展名
SHAPEFILE_EXTENSIONS = {
    ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".sbn", ".sbx", ".fbn", ".fbx", ".ain",
    ".aih", ".ixs", ".mxs", ".atx"
}


def get_arcgis_processes():
    """
    获取系统中所有 ArcGIS Pro / ArcMap 相关的进程列表
    返回: list of dict -> [{'pid': int, 'name': str, 'exe': str}]
    """
    procs = []
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            creationflags=subprocess.CREATE_NO_WINDOW
        ).decode("gbk", errors="ignore")

        target_names = ["arcgispro.exe", "arcgishost.exe", "arcgisworker.exe", "arcmap.exe"]
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip(' "') for p in line.split('","')]
            if len(parts) >= 2:
                pname = parts[0].lower()
                for target in target_names:
                    if target in pname:
                        try:
                            pid = int(parts[1])
                            procs.append({
                                'pid': pid,
                                'name': parts[0],
                                'exe': parts[0]
                            })
                        except ValueError:
                            pass
    except Exception as e:
        logger.error(f"查询系统进程失败: {e}")

    return procs


import re

def identify_dataset_from_path(file_path):
    """
    根据文件路径识别其所属的地理数据集：
    1. 若路径祖先中含有 .gdb 目录，归属为 ('File GDB', gdb_dir)
    2. 若属于 Shapefile 锁文件 (如 xxx.shp.xxx.sr.lock, xxx.shp.lock)，归属为 ('Shapefile', shp_path)
    3. 若扩展名属于 Shapefile 族实体文件，归属为 ('Shapefile', shp_path)
    4. 否则返回 (None, None)
    """
    norm_path = os.path.normpath(file_path)

    # 1. 检测 File GDB
    curr = norm_path
    while True:
        parent = os.path.dirname(curr)
        if curr.lower().endswith(".gdb"):
            return "File GDB", curr
        if not parent or parent == curr:
            break
        curr = parent

    # 2. 检测 Shapefile 锁文件 (例如 xxx.shp.MYPC.1234.sr.lock 或 xxx.shp.lock 等)
    dir_name, file_name = os.path.split(norm_path)
    file_name_lower = file_name.lower()

    if file_name_lower.endswith(".lock"):
        match = re.search(r"^(.*?)\.(shp|dbf)(\..*)?\.lock$", file_name, re.IGNORECASE)
        if match:
            base_prefix = match.group(1)
            shp_canonical = os.path.join(dir_name, base_prefix + ".shp")
            return "Shapefile", shp_canonical

    # 3. 检测直接打开的 Shapefile 实体文件
    base_name, ext = os.path.splitext(file_name)
    ext_lower = ext.lower()

    if ext_lower in SHAPEFILE_EXTENSIONS:
        shp_canonical = os.path.join(dir_name, base_name + ".shp")
        return "Shapefile", shp_canonical

    return None, None


def scan_locked_datasets_for_process(pid):
    """
    扫描某个进程正在锁定的所有地理数据集 (File GDB / Shapefile)
    返回: dict -> {
        dataset_path: {
            'type': 'File GDB' | 'Shapefile',
            'handles': [{'handle': hv, 'path': path}],
            'lock_files': [...]
        }
    }
    """
    results = {}
    locked_files = handle_closer.find_locked_files_in_process(pid)

    for item in locked_files:
        path = item['path']
        hv = item['handle']

        dtype, dpath = identify_dataset_from_path(path)
        if not dtype or not dpath:
            continue

        if dpath not in results:
            results[dpath] = {
                'type': dtype,
                'handles': [],
                'lock_files': []
            }
        results[dpath]['handles'].append({'handle': hv, 'path': path})

    # 为识别到的每个数据集检索对应的 .lock 文件
    for dpath, data in results.items():
        dtype = data['type']
        if dtype == "File GDB":
            if os.path.exists(dpath):
                data['lock_files'] = glob.glob(os.path.join(dpath, "*.lock"))
        elif dtype == "Shapefile":
            dir_name, file_name = os.path.split(dpath)
            base_name, _ = os.path.splitext(file_name)
            # Shapefile 锁文件特征：roads.shp.*.lock 或 roads.*.lock
            lock_pattern1 = os.path.join(dir_name, f"{base_name}.shp.*.lock")
            lock_pattern2 = os.path.join(dir_name, f"{base_name}.*.lock")
            matched = set(glob.glob(lock_pattern1) + glob.glob(lock_pattern2))
            data['lock_files'] = list(matched)

    return results


def scan_all_arcgis_locks():
    """
    扫描所有 ArcGIS Pro 进程的地理数据集锁定情况
    返回: list of dict
    [
        {
            'pid': pid,
            'process_name': str,
            'dataset_type': 'File GDB' | 'Shapefile',
            'dataset_path': str,
            'handles': [{'handle': hv, 'path': path}],
            'lock_files': [path, ...]
        },
        ...
    ]
    """
    all_locks = []
    procs = get_arcgis_processes()

    for p in procs:
        pid = p['pid']
        dataset_map = scan_locked_datasets_for_process(pid)
        for dpath, data in dataset_map.items():
            all_locks.append({
                'pid': pid,
                'process_name': p['name'],
                'dataset_type': data['type'],
                'dataset_path': dpath,
                'handles': data['handles'],
                'lock_files': data['lock_files']
            })

    return all_locks


def release_dataset_lock(pid, dataset_type, dataset_path, handles):
    """
    释放指定进程对某数据集 (File GDB 或 Shapefile) 的锁定：
    1. 强制关闭所有关联句柄
    2. 尝试删除所有残留的关联 .lock 文件
    3. 验证是否可独占访问
    返回: (bool, str) -> (是否完全释放, 描述消息)
    """
    msg_lines = []
    success_count = 0
    fail_count = 0

    # 1. 关闭所有句柄
    for h_info in handles:
        hv = h_info['handle']
        ok = handle_closer.close_remote_handle(pid, hv)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    msg_lines.append(f"句柄关闭结果: 成功 {success_count} 个, 失败 {fail_count} 个")

    # 2. 清理残留 .lock 文件
    lock_files = []
    if dataset_type == "File GDB":
        if os.path.exists(dataset_path):
            lock_files = glob.glob(os.path.join(dataset_path, "*.lock"))
    elif dataset_type == "Shapefile":
        dir_name, file_name = os.path.split(dataset_path)
        base_name, _ = os.path.splitext(file_name)
        pattern1 = os.path.join(dir_name, f"{base_name}.shp.*.lock")
        pattern2 = os.path.join(dir_name, f"{base_name}.*.lock")
        lock_files = list(set(glob.glob(pattern1) + glob.glob(pattern2)))

    deleted_locks = 0
    locked_remains = 0
    for lf in lock_files:
        try:
            os.remove(lf)
            deleted_locks += 1
        except Exception as e:
            locked_remains += 1
            logger.warning(f"删除锁文件 {os.path.basename(lf)} 失败: {e}")

    if lock_files:
        msg_lines.append(f"锁文件清理: 成功删除 {deleted_locks} 个, 仍被占用 {locked_remains} 个")
    else:
        msg_lines.append("未发现残留 .lock 文件")

    # 3. 验证是否真正获得独占写访问权限
    is_free, test_msg = verify_dataset_writable(dataset_type, dataset_path)
    msg_lines.append(f"独占性验证: {test_msg}")

    return is_free, "\n".join(msg_lines)


def verify_dataset_writable(dataset_type, dataset_path):
    """
    尝试以独占读写模式对数据集进行检测
    - File GDB: 在目录下创建并删除测试标记文件
    - Shapefile: 以独占读写模式打开 .shp 或 .dbf 文件
    """
    if dataset_type == "File GDB":
        if not os.path.exists(dataset_path):
            return False, "GDB 路径不存在"

        test_file = os.path.join(dataset_path, "_exclusive_lock_test.tmp")
        try:
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            return True, "已获得完全独占读写权限"
        except PermissionError:
            return False, "仍存在进程或系统句柄占用该 GDB 目录"
        except Exception as e:
            return False, f"GDB 测试异常: {e}"

    elif dataset_type == "Shapefile":
        # 寻找存在的主文件 (.shp 或 .dbf)
        target_file = dataset_path
        if not os.path.exists(target_file):
            dir_name, file_name = os.path.split(dataset_path)
            base_name, _ = os.path.splitext(file_name)
            dbf_file = os.path.join(dir_name, base_name + ".dbf")
            if os.path.exists(dbf_file):
                target_file = dbf_file
            else:
                return False, "Shapefile 目标文件不存在"

        try:
            # 尝试以独占更新模式打开目标文件
            with open(target_file, "r+b") as f:
                pass
            return True, "已获得完全独占读写权限"
        except PermissionError:
            return False, "仍存在句柄占用 Shapefile 文件"
        except Exception as e:
            return False, f"Shapefile 测试异常: {e}"

    return False, "未知数据类型"
