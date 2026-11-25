"""CLI 入口与编排。"""

from __future__ import annotations

import argparse
import sys

import requests

from . import bilibili
from .auth import AuthTimeout, Credentials, NotLoggedIn, UA, ensure_login, load as load_creds
from .bilibili import (
    BiliError,
    area_list,
    room_id_of,
    room_live_status,
    start_live,
    stop_live,
    user_uid,
)
from .config import Config, Paths, load as load_config, save as save_config
from .obs import ObsError, ensure_running, read_ws_password, stop_stream, sync_stream, wait_streaming
from .qr import render_terminal
from .state import clear as clear_state, load as load_state, save as save_state
from .ui import fail, info, mask, ok

LIVE_URL = "https://live.bilibili.com/{room_id}"

AREA_HINT = (
    "尚未设置分区。带 --area <分区id> 运行一次即可记住；\n"
    "  或先看分区表：bls doctor --areas"
)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    return session


def _require_area(cfg: Config, override: int | None) -> int:
    area = override or cfg.area_id
    if not area:
        raise SystemExit(AREA_HINT)
    return int(area)


def _resolve_room(session, creds: Credentials) -> int:
    uid = user_uid(session, creds)
    room_id = room_id_of(session, creds, uid)
    if not room_id:
        raise BiliError(-1, "取不到直播间号")
    return room_id


def _area_name(session, area_id: int) -> str:
    for _, _, children in area_list(session):
        for cid, name in children:
            if cid == area_id:
                return name
    return "未知分区"


def cmd_login(args, paths: Paths) -> int:
    session = make_session()
    try:
        creds = ensure_login(session, paths, interactive=True)
    except (AuthTimeout, NotLoggedIn) as exc:
        fail(str(exc))
        return 1
    ok(f"登录有效（UID {creds.dede_user_id}）")
    return 0


def cmd_go(args, paths: Paths) -> int:
    cfg = load_config(paths)
    area_id = _require_area(cfg, args.area)
    if args.area and args.area != cfg.area_id:
        cfg.area_id = args.area
        save_config(cfg, paths)
        info(f"已记住分区 {args.area}")
    session = make_session()

    try:
        creds = ensure_login(session, paths, interactive=True)
    except (AuthTimeout, NotLoggedIn) as exc:
        fail(str(exc))
        return 1
    ok(f"登录有效（UID {creds.dede_user_id}）")

    try:
        room_id = _resolve_room(session, creds)
    except BiliError as exc:
        fail(f"取不到直播间号：{exc.message}")
        info(exc.hint)
        return 1

    if args.dry_run:
        info(f"[dry-run] 会为房间 {room_id} 开播，分区 {area_id}（{_area_name(session, area_id)}）")
        info("[dry-run] 不会调用开播接口，也不会启动 OBS")
        return 0

    saved = load_state(paths.state_file)
    if room_live_status(session, room_id) == 1:
        if saved and int(saved.get("room_id") or 0) == room_id:
            info("B 站已在开播，复用上次推流码")
            stream = bilibili.StreamInfo(
                addr=saved["addr"],
                code=saved["code"],
                room_id=room_id,
                live_key=str(saved.get("live_key") or ""),
            )
            return _stream_to_obs(stream, paths)

        fail("B 站已开播，但本机没有推流码记录")
        info("继续会重新开播，可能中断当前推流")
        if not args.force:
            if not sys.stdin.isatty():
                info("非交互环境已中止；确认要重开请加 --force")
                return 1
            answer = input("  继续？[y/N] ").strip().lower()
            if answer != "y":
                return 1

    return _start_and_stream(session, creds, room_id, area_id, paths)


def _wait_face_auth(exc: BiliError, uid: str) -> bool:
    """提示人脸认证，返回 True 表示可以立刻重试开播。"""
    fail(f"B 站要求人脸认证：{exc.message}（code {exc.code}）")
    url = exc.face_auth_qr
    if not url and exc.code == 60043 and uid:
        url = bilibili.face_auth_url(uid)
    if url:
        info("用手机 B 站 App 扫下面的码，按提示完成人脸认证")
        print(render_terminal(url))
        info(f"认证地址：{url}")
    elif exc.code == 60024:
        info("该分区强制人脸认证。手机 App 完成一次认证后重试，或用 --area 换一个分区")
    else:
        info("B 站这次的响应里没有认证链接，需要在手机 App 开播时按提示做人脸")
    if not sys.stdin.isatty():
        info("非交互环境，无法原地重试；完成认证后重新运行 bls go")
        return False
    answer = input("  认证完成后回车重试，输入 q 放弃：").strip().lower()
    return answer != "q"


def _start_and_stream(session, creds: Credentials, room_id: int, area_id: int, paths: Paths) -> int:
    while True:
        try:
            stream = start_live(session, creds, room_id, area_id)
            break
        except BiliError as exc:
            if exc.code in bilibili.FACE_AUTH_CODES and _wait_face_auth(exc, creds.dede_user_id):
                continue
            fail(f"开播失败：{exc.message}（code {exc.code}）")
            if exc.hint:
                info(exc.hint)
            info("未启动 OBS（B 站端未开播）")
            return 1
    ok(f"开播成功  房间 {stream.room_id}  分区 {area_id}")
    save_state(
        paths.state_file,
        addr=stream.addr,
        code=stream.code,
        room_id=stream.room_id,
        live_key=stream.live_key,
    )
    return _stream_to_obs(stream, paths)


def _stream_to_obs(stream: bilibili.StreamInfo, paths: Paths) -> int:
    cfg = load_config(paths)
    try:
        client = ensure_running(cfg, paths.obs_config_dir, launch_obs=cfg.launch_obs)
    except ObsError as exc:
        fail(f"OBS 没起来：{exc.comment}")
        info("B 站端已经开播，观众会看到黑屏")
        info("收尾：bls stop --bili-only")
        return 1

    try:
        ok(f"已连接 OBS（{cfg.obs_port}）")
        result = sync_stream(client, stream.addr, stream.code)
        label = {
            "unchanged": "推流已在运行，推流码一致",
            "restarted": "推流码不一致，已重启推流",
            "started": "已开始推流",
        }[result]
        ok(f"推流码已写入  {label}")
        if not wait_streaming(client):
            fail("OBS 已开始推流，但数据没有发出去")
            info("常见原因：推流地址失效、网络不通、码率过高")
            info("B 站端仍处于开播状态；需要收尾请运行 bls stop")
            return 1
        ok("数据已发出")
        info(f"→ {LIVE_URL.format(room_id=stream.room_id)}")
        return 0
    finally:
        client.close()


def cmd_stop(args, paths: Paths) -> int:
    cfg = load_config(paths)
    session = make_session()
    saved = load_state(paths.state_file) or {}
    room_id = args.room or saved.get("room_id")
    rc = 0

    if not args.bili_only:
        try:
            client = ensure_running(cfg, paths.obs_config_dir, launch_obs=False)
        except ObsError as exc:
            info(f"跳过 OBS：{exc.comment}")
        else:
            try:
                if stop_stream(client):
                    ok("已停止 OBS 推流")
                else:
                    info("OBS 本来就没在推流")
            finally:
                client.close()

    if not args.obs_only:
        creds = load_creds(paths.credentials_file)
        if creds is None:
            info("跳过 B 站：尚未登录")
        elif not room_id:
            fail("不知道直播间号，用 --room 指定")
            rc = 1
        else:
            try:
                stop_live(session, creds, int(room_id))
            except BiliError as exc:
                fail(f"关播失败：{exc.message}（code {exc.code}）")
                rc = 1
            else:
                ok(f"B 站已关播  房间 {room_id}")
                clear_state(paths.state_file)
                ok("已清除本机推流码记录")
    return rc


def cmd_status(args, paths: Paths) -> int:
    creds = load_creds(paths.credentials_file)
    if creds is None:
        info("登录：无，先运行 bls login")
        return 1
    session = make_session()
    try:
        uid = user_uid(session, creds)
    except BiliError as exc:
        info(f"登录校验：失败（{exc.code} {exc.message}）")
        return 1
    ok(f"登录有效（UID {uid}）")

    saved = load_state(paths.state_file)
    room_id = None
    try:
        room_id = room_id_of(session, creds, uid)
    except BiliError as exc:
        info(f"直播间：取不到（{exc.code} {exc.message}）")
        if saved and saved.get("room_id"):
            room_id = int(saved["room_id"])
            info(f"直播间：{room_id}（取自本机推流码记录）")
    else:
        info(f"直播间：{room_id}")
    if room_id is not None:
        try:
            status = room_live_status(session, room_id)
        except BiliError as exc:
            info(f"B 站状态：查不到（{exc.code} {exc.message}）")
        else:
            info(f"B 站状态：{'直播中' if status == 1 else ('轮播中' if status == 2 else '未开播')}")

    cfg = load_config(paths)
    try:
        client = ensure_running(cfg, paths.obs_config_dir, launch_obs=False)
    except ObsError as exc:
        info(f"OBS：{exc.comment}")
    else:
        try:
            stream_status = client.call("GetStreamStatus")
            info(f"OBS：推流中" if stream_status.get("outputActive") else "OBS：未推流")
        finally:
            client.close()

    saved = load_state(paths.state_file)
    info(f"本机推流码记录：{'有' if saved else '无'}")
    return 0


def cmd_doctor(args, paths: Paths) -> int:
    issues = 0
    cfg = load_config(paths)

    binary = shutil_which(cfg.obs_binary)
    if binary:
        ok(f"OBS 可执行：{binary}")
    else:
        fail(f"找不到 OBS 可执行文件：{cfg.obs_binary}")
        issues += 1

    profiles = paths.obs_config_dir / "basic" / "profiles"
    if profiles.exists() and any(profiles.iterdir()):
        ok("OBS 已完成首次启动（存在 profile）")
    else:
        fail("OBS 还没完成首次启动：先手动打开一次 OBS 完成向导")
        issues += 1

    enabled, password = read_ws_password(paths.obs_config_dir)
    if enabled:
        ok(f"obs-websocket 已启用（端口 {cfg.obs_port}，密码 {mask(password)}）")
    else:
        fail("obs-websocket 未启用：OBS → 工具 → WebSocket 服务器设置")
        issues += 1

    creds = load_creds(paths.credentials_file)
    if creds is None:
        info("尚未登录，运行 bls login")
    else:
        session = make_session()
        try:
            uid = user_uid(session, creds)
            ok(f"登录有效（UID {uid}）")
            if args.areas:
                for _, parent_name, children in area_list(session):
                    print(f"  {parent_name}")
                    for cid, name in children:
                        print(f"    {cid:<6} {name}")
            elif cfg.area_id:
                found = False
                for _, _, children in area_list(session):
                    if any(cid == cfg.area_id for cid, _ in children):
                        found = True
                        break
                if found:
                    ok(f"分区 {cfg.area_id} 存在")
                else:
                    fail(f"分区 {cfg.area_id} 已不存在，用 --area 重新选一个")
                    issues += 1
            else:
                info("尚未设置分区，运行 bls doctor --areas 查看分区表")
        except BiliError as exc:
            fail(f"登录失效：{exc.message}（code {exc.code}）")
            issues += 1
    return 0 if issues == 0 else 1


def shutil_which(binary: str) -> str | None:
    import shutil

    return shutil.which(binary)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bls",
        description="B 站一键开播：调接口开播 → 拉起 OBS → 自动填写推流码",
    )
    parser.add_argument("--version", action="version", version="bls 0.1.0")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("login", help="扫码登录并保存登录态")

    go = sub.add_parser("go", help="开播并把推流码写进 OBS")
    go.add_argument("--area", type=int, default=None, help="直播分区 id（会记住）")
    go.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    go.add_argument("--force", action="store_true", help="B 站已开播且无记录时也继续")

    stop = sub.add_parser("stop", help="停止推流并关播")
    stop.add_argument("--bili-only", action="store_true", help="只关 B 站端")
    stop.add_argument("--obs-only", action="store_true", help="只停 OBS 推流")
    stop.add_argument("--room", type=int, default=None, help="直播间号")

    sub.add_parser("status", help="查看登录、B 站与 OBS 状态")

    doctor = sub.add_parser("doctor", help="环境体检")
    doctor.add_argument("--areas", action="store_true", help="打印分区表")

    return parser


COMMANDS = {
    "login": cmd_login,
    "go": cmd_go,
    "stop": cmd_stop,
    "status": cmd_status,
    "doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return COMMANDS[args.command](args, Paths())


if __name__ == "__main__":
    sys.exit(main())
