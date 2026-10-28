#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File: video_transcoder.py
    @Author: liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date: 2026/10/1
    @Desc:
        视频转 HLS 工具
     输入:
        original.mp4
     输出:
        play_list.m3u8
        cover.jpg

        360p/
            index.m3u8
            init.mp4
            segment_00000.m4s
            ...

        480p/
            index.m3u8
            init.mp4
            ...

        720p/
            index.m3u8
            init.mp4
            ...

        1080p/
            index.m3u8
            init.mp4
            ...

     特点:
        1. HLS 使用 fMP4
        2. 不会上采样
        3. 支持横屏 / 竖屏 / 正方形
        4. 临时目录和视频目录同级
        5. original.mp4 不会被覆盖
        6. FFmpeg 使用 cwd 保证 HLS 相对路径正确
        7. 转码成功后才正式发布
        8. 支持 HLS 输出校验
=================================================
"""
from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class VideoTranscoderError(RuntimeError):
    """视频转码基础异常"""


class FFprobeError(VideoTranscoderError):
    """ffprobe 异常"""


class FFmpegError(VideoTranscoderError):
    """ffmpeg 异常"""


@dataclass(frozen=True)
class HLSProfile:
    """
    HLS 清晰度配置。
     short_side:
        短边目标尺寸。
        横屏:
            1920x1080 -> 1280x720
        竖屏:
            1080x1920 -> 720x1280
    """
    name: str          # 清晰度名, 同时作为输出子目录名(360p / 480p / 720p / 1080p)
    short_side: int    # 目标短边像素; 只做缩小, 不做放大(见 select_profiles)
    bitrate: str       # 视频目标码率, 形如 "2800k"
    audio_bitrate: str = "128k"  # 音频目标码率; 源视频无音轨时不会被使用


@dataclass
class VideoInfo:
    """ffprobe 探测结果。

    宽高已在 probe() 中按旋转元数据做过交换, 因此这里的 width/height
    就是「播放器实际看到的画面方向」, 后续 calc_size 直接按此比例缩放。
    """
    width: int                          # 画面宽(已按旋转角校正)
    height: int                         # 画面高(已按旋转角校正)
    duration: float                     # 时长(秒), 取容器时长, 缺失时退回视频流时长
    fps: float                          # 平均帧率, 解析失败按 25.0 兜底(影响 GOP 计算)
    audio: bool                         # 是否存在音频流, 决定是否加 -c:a 参数
    video_codec: Optional[str] = None   # 视频编码名, 如 h264 / hevc
    audio_codec: Optional[str] = None   # 音频编码名, 无音轨为 None
    rotation: int = 0                   # 旋转角(0/90/180/270), 已归一化为 abs(x) % 360

    @property
    def short_side(self) -> int:
        """短边尺寸: 清晰度选择的依据(横屏看 height, 竖屏看 width)。"""
        return min(self.width, self.height)

    @property
    def long_side(self) -> int:
        """长边尺寸。"""
        return max(self.width, self.height)

    @property
    def is_portrait(self) -> bool:
        """是否竖屏(高 > 宽)。"""
        return self.height > self.width

    @property
    def is_landscape(self) -> bool:
        """是否横屏(宽 > 高)。"""
        return self.width > self.height

    @property
    def is_square(self) -> bool:
        """是否正方形(宽 == 高), 缩放时宽高取同一目标值。"""
        return self.width == self.height


@dataclass
class HLSVariant:
    """单条清晰度的转码产物描述, 用于拼装 master playlist。

    playlist 是相对 master 的路径(如 "720p/index.m3u8"), 因为 ffmpeg 以
    变体目录为 cwd 生成分片, 相对路径才能被播放器正确解析。
    """
    name: str          # 清晰度名, 对应输出子目录
    width: int         # 实际输出宽(偶数化之后)
    height: int        # 实际输出高(偶数化之后)
    bitrate: str       # 视频码率, 形如 "2800k"
    audio_bitrate: str # 音频码率; 源无音轨时为 "0"
    playlist: str      # 变体 playlist 相对路径, 如 "720p/index.m3u8"


@dataclass
class TranscodeResult:
    """一次完整转码的结果, 供调用方落库/回调使用。"""
    playlist: str             # master playlist 的绝对路径(play_list.m3u8)
    cover: str                # 封面绝对路径; generate_cover=False 时为空字符串
    info: VideoInfo           # 源视频探测信息(宽高已校正)
    variants: List[HLSVariant]  # 实际产出的各清晰度, 可能少于 DEFAULT_PROFILES


class VideoTranscoder:
    """
    视频 HLS 转码器。
     推荐目录结构:
         videos/
        └── 202610/
            └── video-id/
                ├── original.mp4
                ├── play_list.m3u8
                ├── cover.jpg
                │
                ├── 360p/
                │   ├── index.m3u8
                │   ├── init.mp4
                │   └── *.m4s
                │
                ├── 480p/
                │   ├── index.m3u8
                │   ├── init.mp4
                │   └── *.m4s
                │
                ├── 720p/
                │   ├── index.m3u8
                │   ├── init.mp4
                │   └── *.m4s
                │
                └── 1080p/
                    ├── index.m3u8
                    ├── init.mp4
                    └── *.m4s
    """

    DEFAULT_PROFILES: Sequence[HLSProfile] = (
        HLSProfile(
            name="360p",
            short_side=360,
            bitrate="800k",
        ),
        HLSProfile(
            name="480p",
            short_side=480,
            bitrate="1200k",
        ),
        HLSProfile(
            name="720p",
            short_side=720,
            bitrate="2800k",
        ),
        HLSProfile(
            name="1080p",
            short_side=1080,
            bitrate="5000k",
        ),
    )

    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        threads: Optional[int] = 4,
        preset: str = "fast",
        segment_time: int = 4,
    ):
        """
        Args:
            ffmpeg: ffmpeg 可执行文件(裸命令名走 PATH, 也可传绝对路径)
            ffprobe: ffprobe 可执行文件, 同上
            threads: 编码线程数; None 表示交给 ffmpeg 自选
            preset: libx264 预设(ultrafast..veryslow), 越慢压缩率越高
            segment_time: HLS 分片时长(秒), 同时决定关键帧间隔

        Raises:
            FileNotFoundError: ffmpeg / ffprobe 不可用
        """
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.threads = threads
        self.preset = preset
        self.segment_time = segment_time

        self._validate_executable(self.ffmpeg, "ffmpeg")
        self._validate_executable(self.ffprobe, "ffprobe")

    # ============================================================
    # Public API
    # ============================================================
    def convert(
        self,
        input_file: str | Path,
        output_dir: str | Path,
        profiles: Optional[Sequence[HLSProfile]] = None,
        generate_cover: bool = True,
        overwrite: bool = True,
    ) -> TranscodeResult:
        """
        将原始视频转换成 HLS。
         Args:
            input_file:
                原始视频，例如:
                /videos/xxx/original.mp4
             output_dir:
                视频输出目录，例如:
                /videos/xxx/
             profiles:
                HLS 清晰度配置。
             generate_cover:
                是否生成 cover.jpg。
             overwrite:
                输出目录已有 HLS 文件时是否覆盖。
         Returns:
            TranscodeResult
        """
        input_path = Path(input_file).resolve()
        output_path = Path(output_dir).resolve()

        self._validate_input(input_path)

        # 防止 output_dir 和 input_file 本身冲突
        if output_path == input_path:
            raise ValueError("output_dir cannot be the same as input_file")

        logger.info(
            "开始视频转码: input=%s, output=%s",
            input_path,
            output_path,
        )

        # --------------------------------------------------------
        # 探测视频
        # --------------------------------------------------------
        info = self.probe(input_path)

        logger.info(
            "视频信息: %sx%s, duration=%.2fs, fps=%.2f, audio=%s",
            info.width,
            info.height,
            info.duration,
            info.fps,
            info.audio,
        )

        profiles = profiles or self.DEFAULT_PROFILES
        selected_profiles = self.select_profiles(info, profiles)

        logger.info(
            "选择清晰度: %s",
            [p.name for p in selected_profiles],
        )

        # --------------------------------------------------------
        # 输出目录
        # --------------------------------------------------------
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # --------------------------------------------------------
        # 如果不允许覆盖，直接检查
        # --------------------------------------------------------
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"output directory already exists: {output_path}")

        # --------------------------------------------------------
        # 临时目录
        #
        # 注意:
        # 临时目录与 output 同级，而不是:
        #
        # output/
        # └── temp/
        #
        # 这样最终发布更加安全。
        # --------------------------------------------------------
        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{output_path.name}.transcoding-",
                dir=output_path.parent,
            )
        )

        logger.info("创建临时目录: %s", temp_dir)

        try:
            variants: List[HLSVariant] = []

            # ----------------------------------------------------
            # 转码各清晰度
            # ----------------------------------------------------
            for profile in selected_profiles:
                variant = self.convert_profile(
                    input_file=input_path,
                    output=temp_dir,
                    profile=profile,
                    info=info,
                )
                variants.append(variant)

            # ----------------------------------------------------
            # 创建 Master Playlist
            # ----------------------------------------------------
            self.create_master_playlist(
                output=temp_dir,
                variants=variants,
                has_audio=info.audio,
            )

            # ----------------------------------------------------
            # 创建封面
            # ----------------------------------------------------
            cover_path = temp_dir / "cover.jpg"

            if generate_cover:
                self.create_cover(
                    input_file=input_path,
                    output=cover_path,
                    duration=info.duration,
                )

            # ----------------------------------------------------
            # 验证 HLS
            # ----------------------------------------------------
            self.validate_hls(
                output=temp_dir,
                variants=variants,
            )

            # ----------------------------------------------------
            # 发布
            #
            # 注意:
            # original.mp4 已经存在于 output_path。
            #
            # 所以不能:
            #
            # temp.rename(output)
            #
            # 否则会把 original.mp4 一起覆盖掉。
            #
            # 这里采用:
            #
            # temp/
            #   play_list.m3u8
            #   cover.jpg
            #   360p/
            #
            # 然后只把 HLS 产物复制/移动到 output。
            # ----------------------------------------------------
            self.publish(
                temp_dir=temp_dir,
                output_dir=output_path,
                overwrite=overwrite,
            )

            result = TranscodeResult(
                playlist=str(output_path / "play_list.m3u8"),
                cover=str(output_path / "cover.jpg") if generate_cover else "",
                info=info,
                variants=variants,
            )

            logger.info("视频转码完成: %s", result.playlist)
            return result

        except Exception:
            logger.exception("视频转码失败: %s", input_path)
            raise
        finally:
            # ----------------------------------------------------
            # 清理临时目录
            # ----------------------------------------------------
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ============================================================
    # ffprobe
    # ============================================================
    def probe(
        self,
        input_file: str | Path,
    ) -> VideoInfo:
        """
        获取视频基本信息。
        """
        input_path = Path(input_file).resolve()

        cmd = [
            self.ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(input_path),
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise FFprobeError(
                "ffprobe 执行失败:\n"
                f"file: {input_path}\n"
                f"error: {result.stderr.strip()}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FFprobeError(f"ffprobe 返回的数据无法解析: {input_path}") from exc

        streams = data.get("streams", [])
        video_stream = None
        audio_stream = None

        for stream in streams:
            codec_type = stream.get("codec_type")
            if codec_type == "video" and video_stream is None:
                video_stream = stream
            elif codec_type == "audio" and audio_stream is None:
                audio_stream = stream

        if not video_stream:
            raise FFprobeError(f"文件不存在视频流: {input_path}")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        if width <= 0 or height <= 0:
            raise FFprobeError(f"视频分辨率无效: {width}x{height}")

        duration = self._parse_float(data.get("format", {}).get("duration"))
        if duration <= 0:
            duration = self._parse_float(video_stream.get("duration"))

        fps = self._parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        rotation = self._parse_rotation(video_stream)

        # --------------------------------------------------------
        # 手机视频经常带 90 / 270 度旋转 metadata。
        #
        # FFmpeg 默认会根据 metadata 自动旋转，
        # 所以这里同步交换宽高。
        # --------------------------------------------------------
        if rotation in (90, 270):
            width, height = height, width

        return VideoInfo(
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            audio=audio_stream is not None,
            video_codec=video_stream.get("codec_name"),
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            rotation=rotation,
        )

    # ============================================================
    # 选择清晰度
    # ============================================================
    def select_profiles(
        self,
        info: VideoInfo,
        profiles: Sequence[HLSProfile],
    ) -> List[HLSProfile]:
        """
        根据源视频短边选择清晰度。
         例如:
          1920x1080:
            360p
            480p
            720p
            1080p
          1280x720:
            360p
            480p
            720p
          1080x1920:
            360p
            480p
            720p
            1080p
          640x360:
            360p
          320x180:
            动态生成 180p
        """
        sorted_profiles = sorted(profiles, key=lambda p: p.short_side)
        selected = [profile for profile in sorted_profiles if profile.short_side <= info.short_side]

        # --------------------------------------------------------
        # 源视频小于最低清晰度。
        #
        # 例如:
        #
        # 320x180
        #
        # 不允许放大成 360p。
        # --------------------------------------------------------
        if not selected:
            lowest = sorted_profiles[0]
            native_short_side = info.short_side
            selected = [
                HLSProfile(
                    name=f"{native_short_side}p",
                    short_side=native_short_side,
                    bitrate=lowest.bitrate,
                    audio_bitrate=lowest.audio_bitrate,
                )
            ]
        return selected

    # ============================================================
    # 单个清晰度转码
    # ============================================================
    def convert_profile(
        self,
        input_file: Path,
        output: Path,
        profile: HLSProfile,
        info: VideoInfo,
    ) -> HLSVariant:
        """把源视频转码成单个清晰度的 fMP4 HLS 变体。

        输出写入 output/<profile.name>/, 内含 index.m3u8 + init.mp4 + segment_*.m4s。

        Args:
            input_file: 源视频绝对路径
            output: 转码临时根目录(各清晰度在此下建子目录)
            profile: 该档清晰度配置
            info: 源视频信息, 用于算目标尺寸与 GOP 帧数

        Returns:
            HLSVariant: 供 master playlist 使用的变体描述

        Raises:
            FFmpegError: ffmpeg 返回非 0, 或 playlist / init.mp4 未生成
        """
        folder = output / profile.name
        folder.mkdir(parents=True, exist_ok=True)

        width, height = self.calc_size(info, profile.short_side)
        playlist = folder / "index.m3u8"

        logger.info("开始转码 %s: %sx%s", profile.name, width, height)

        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_file),
            # 只取第一个视频
            "-map",
            "0:v:0",
            # 编码线程
            *(["-threads", str(self.threads)] if self.threads else []),
            # ----------------------------------------------------
            # Scale
            # ----------------------------------------------------
            "-vf",
            f"scale={width}:{height}:flags=lanczos",
            # ----------------------------------------------------
            # H264
            # ----------------------------------------------------
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "main",
            "-b:v",
            profile.bitrate,
            # 控制码率波动
            "-maxrate",
            self._calculate_maxrate(profile.bitrate),
            "-bufsize",
            self._calculate_bufsize(profile.bitrate),
            # ----------------------------------------------------
            # GOP
            # ----------------------------------------------------
            "-g",
            str(max(1, round(info.fps * self.segment_time))),
            "-keyint_min",
            str(max(1, round(info.fps * self.segment_time))),
            "-sc_threshold",
            "0",
            # 保证分片附近有关键帧
            "-force_key_frames",
            f"expr:gte(t,n_forced*{self.segment_time})",
        ]

        # --------------------------------------------------------
        # Audio
        # --------------------------------------------------------
        if info.audio:
            cmd += [
                "-map",
                "0:a:0?",
                "-c:a",
                "aac",
                "-b:a",
                profile.audio_bitrate,
                "-ar",
                "48000",
                "-ac",
                "2",
            ]
        else:
            cmd.append("-an")

        # --------------------------------------------------------
        # HLS fMP4
        #
        # cwd=folder
        #
        # 因此这里必须使用相对路径:
        #
        # init.mp4
        # segment_00000.m4s
        # index.m3u8
        #
        # 最终都会生成到:
        #
        # output/720p/
        # --------------------------------------------------------
        cmd += [
            "-f",
            "hls",
            "-hls_time",
            str(self.segment_time),
            "-hls_playlist_type",
            "vod",
            "-hls_list_size",
            "0",
            "-hls_segment_type",
            "fmp4",
            "-hls_fmp4_init_filename",
            "init.mp4",
            "-hls_segment_filename",
            "segment_%05d.m4s",
            "-hls_flags",
            "independent_segments",
            "index.m3u8",
        ]

        self.run(cmd, cwd=folder)

        # --------------------------------------------------------
        # 基础检查
        # --------------------------------------------------------
        if not playlist.exists():
            raise FFmpegError(f"{profile.name} HLS playlist 未生成: {playlist}")
        init_file = folder / "init.mp4"
        if not init_file.exists():
            raise FFmpegError(f"{profile.name} init.mp4 未生成: {init_file}")

        return HLSVariant(
            name=profile.name,
            width=width,
            height=height,
            bitrate=profile.bitrate,
            audio_bitrate=profile.audio_bitrate if info.audio else "0",
            playlist=f"{profile.name}/index.m3u8",
        )

    # ============================================================
    # Master Playlist
    # ============================================================
    def create_master_playlist(
        self,
        output: Path,
        variants: Sequence[HLSVariant],
        has_audio: bool,
    ) -> Path:
        """生成多码率入口 play_list.m3u8。

        码率声明取 maxrate(目标码率 x1.1) + 音频码率: BANDWIDTH 是播放器选流的
        硬门槛, 取实际峰值而非平均值, 否则弱网下会选到跑不动的档位。
        变体按清晰度从高到低写入(播放器默认取第一条), 所以这里 reversed 输出。

        Args:
            output: master playlist 输出目录
            variants: 各清晰度产物
            has_audio: 源是否含音轨, 决定是否把音频码率计入 BANDWIDTH

        Returns:
            Path: 生成好的 play_list.m3u8 路径
        """
        playlist = output / "play_list.m3u8"
        with playlist.open("w", encoding="utf-8", newline="\n") as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:7\n")
            f.write("#EXT-X-INDEPENDENT-SEGMENTS\n")

            for variant in reversed(variants):
                video_bitrate = self._bitrate_to_bps(variant.bitrate)
                audio_bitrate = self._bitrate_to_bps(variant.audio_bitrate) if has_audio else 0

                # BANDWIDTH 使用 maxrate + audio
                max_video_bitrate = int(video_bitrate * 1.1)
                bandwidth = max_video_bitrate + audio_bitrate
                average_bandwidth = video_bitrate + audio_bitrate

                f.write(
                    "#EXT-X-STREAM-INF:"
                    f"BANDWIDTH={bandwidth},"
                    f"AVERAGE-BANDWIDTH={average_bandwidth},"
                    f"RESOLUTION={variant.width}x{variant.height}\n"
                )
                f.write(f"{variant.playlist}\n")
        return playlist

    # ============================================================
    # Cover
    # ============================================================
    def create_cover(
        self,
        input_file: Path,
        output: Path,
        duration: float,
    ) -> None:
        """截取一帧作为封面(cover.jpg)。

        取帧位置: 优先第 1 秒, 极短视频(duration<2s)取中点, 避免截到开头的黑帧。
        注意: 这里用 -ss 放在 -i 之前(输入侧 seek), 速度快但精度是最近关键帧。

        Args:
            input_file: 源视频
            output: 封面输出路径
            duration: 源时长, <=0 表示未知, 此时直接从开头截取

        Raises:
            FFmpegError: 未生成封面文件
        """
        if duration <= 0:
            seek = 0
        else:
            # 尽量取 1 秒位置。
            # 极短视频则取中间位置。
            seek = min(1.0, max(0.0, duration / 2))

        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(seek),
            "-i",
            str(input_file),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ]
        self.run(cmd)

        if not output.exists():
            raise FFmpegError(f"封面生成失败: {output}")

    # ============================================================
    # HLS 校验
    # ============================================================
    def validate_hls(
        self,
        output: Path,
        variants: Sequence[HLSVariant],
    ) -> None:
        """发布前的完整性校验(在临时目录上做, 通过后才 publish)。

        逐项检查: master 是否为合法 m3u8 → 每档 index.m3u8 / init.mp4 是否存在且非空
        → playlist 里引用的每个 .m4s 分片是否真实落盘且非空 → 至少有一个媒体分片。
        这一步能在发布前拦住「ffmpeg 退出码 0 但产物残缺」的情况。

        Args:
            output: 临时目录(含 master 与各变体子目录)
            variants: 待校验的变体列表

        Raises:
            VideoTranscoderError: 任一检查项不通过
        """
        master = output / "play_list.m3u8"
        if not master.exists():
            raise VideoTranscoderError(f"Master playlist 不存在: {master}")

        master_content = master.read_text(encoding="utf-8")
        if "#EXTM3U" not in master_content:
            raise VideoTranscoderError("Master playlist 格式错误")

        for variant in variants:
            folder = output / variant.name
            playlist = folder / "index.m3u8"
            init_file = folder / "init.mp4"

            if not playlist.exists():
                raise VideoTranscoderError(f"Variant playlist 不存在: {playlist}")
            if not init_file.exists():
                raise VideoTranscoderError(f"init.mp4 不存在: {init_file}")
            if init_file.stat().st_size <= 0:
                raise VideoTranscoderError(f"init.mp4 为空: {init_file}")

            content = playlist.read_text(encoding="utf-8")
            if "#EXTM3U" not in content:
                raise VideoTranscoderError(f"Playlist 格式错误: {playlist}")

            # ----------------------------------------------------
            # 验证 m4s 分片
            # ----------------------------------------------------
            segment_count = 0
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                segment = folder / line
                if not segment.exists():
                    raise VideoTranscoderError(f"HLS segment 不存在: {segment}")
                if segment.stat().st_size <= 0:
                    raise VideoTranscoderError(f"HLS segment 为空: {segment}")
                segment_count += 1

            if segment_count == 0:
                raise VideoTranscoderError(f"HLS 没有任何媒体分片: {playlist}")

            logger.info("HLS 校验成功: %s, segments=%s", variant.name, segment_count)

    # ============================================================
    # 发布
    # ============================================================
    def publish(
        self,
        temp_dir: Path,
        output_dir: Path,
        overwrite: bool,
    ) -> None:
        """
        将临时目录中的 HLS 产物发布到正式视频目录。
         不会覆盖 original.mp4。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        publish_files = [
            "play_list.m3u8",
            "cover.jpg",
        ]

        for name in publish_files:
            source = temp_dir / name
            if not source.exists():
                continue
            target = output_dir / name
            if target.exists() and overwrite:
                target.unlink()
            shutil.move(str(source), str(target))

        # --------------------------------------------------------
        # 发布各清晰度目录
        # --------------------------------------------------------
        for item in temp_dir.iterdir():
            if not item.is_dir():
                continue
            target = output_dir / item.name
            if target.exists():
                if not overwrite:
                    raise FileExistsError(f"HLS variant already exists: {target}")
                shutil.rmtree(target)
            shutil.move(str(item), str(target))

    # ============================================================
    # FFmpeg 执行
    # ============================================================
    def run(
        self,
        cmd: Sequence[str],
        cwd: Optional[str | Path] = None,
    ) -> None:
        """执行一条 ffmpeg 命令, 非 0 退出码统一转成 FFmpegError。

        stdout/stderr 全部捕获(不打印到控制台), 失败时把 stderr 原样带进异常消息,
        便于定位转码失败原因。cwd 传变体目录, 以支持 HLS 的相对路径输出。

        Args:
            cmd: 完整命令参数序列
            cwd: 子进程工作目录; None 表示沿用当前进程目录

        Raises:
            FFmpegError: ffmpeg 返回非 0(消息内含 returncode / cwd / command / stderr)
        """
        logger.debug("执行 FFmpeg: %s", " ".join(map(str, cmd)))
        result = subprocess.run(
            list(map(str, cmd)),
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            error = result.stderr.strip()
            raise FFmpegError(
                "FFmpeg 执行失败\n"
                f"returncode: {result.returncode}\n"
                f"cwd: {cwd}\n"
                f"command: {' '.join(map(str, cmd))}\n"
                f"stderr:\n{error}"
            )

    # ============================================================
    # 尺寸计算
    # ============================================================
    @staticmethod
    def calc_size(
        info: VideoInfo,
        target_short_side: int,
    ) -> tuple[int, int]:
        """按「锁定短边」的方式等比计算目标宽高。

        锁定短边而不是固定长边, 是为了让竖屏视频也能按同一条清晰度阶梯缩小;
        宽高各自再偶数化, 因为 H.264 + yuv420p 要求尺寸必须是偶数。

        Args:
            info: 源视频信息
            target_short_side: 目标短边像素, 必须 > 0

        Returns:
            tuple[int, int]: (宽, 高), 均为偶数

        Raises:
            ValueError: target_short_side <= 0
        """
        if target_short_side <= 0:
            raise ValueError("target_short_side must be > 0")

        # 正方形
        if info.is_square:
            return (target_short_side, target_short_side)
        # 横屏
        if info.is_landscape:
            height = target_short_side
            width = round(height * info.width / info.height)
        # 竖屏
        else:
            width = target_short_side
            height = round(width * info.height / info.width)

        # H264 / YUV420P 要求偶数尺寸
        width = VideoTranscoder._even(width)
        height = VideoTranscoder._even(height)
        return width, height

    # ============================================================
    # 工具方法
    # ============================================================
    @staticmethod
    def _even(value: int) -> int:
        """向下取到最近的偶数(最小 2), 满足 H.264 / yuv420p 对尺寸的约束。"""
        return max(2, value - (value % 2))

    @staticmethod
    def _parse_float(value) -> float:
        """宽容地把 ffprobe 字段转 float: None / "N/A" / 非法值统一返回 0.0。"""
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_fps(value) -> float:
        """解析帧率。

        ffprobe 的帧率是分数字符串("30000/1001"), 也可能缺失或为 "0/0";
        解析失败一律按 25.0 兜底 —— 该值只用于估算 GOP 帧数, 偏差不影响正确性。
        """
        if not value or value in ("0/0", "N/A"):
            return 25.0
        try:
            if "/" in value:
                numerator, denominator = value.split("/", 1)
                numerator = float(numerator)
                denominator = float(denominator)
                if denominator == 0:
                    return 25.0
                return numerator / denominator
            return float(value)
        except (TypeError, ValueError):
            return 25.0

    @staticmethod
    def _parse_rotation(stream: Dict) -> int:
        # 老版本 ffprobe
        tags = stream.get("tags") or {}
        rotation = tags.get("rotate")
        if rotation is not None:
            try:
                rotation = int(rotation)
                return abs(rotation) % 360
            except (TypeError, ValueError):
                pass
        # 新版本 ffprobe
        side_data_list = stream.get("side_data_list") or []
        for side_data in side_data_list:
            rotation = side_data.get("rotation")
            if rotation is not None:
                try:
                    rotation = int(rotation)
                    return abs(rotation) % 360
                except (TypeError, ValueError):
                    pass
        return 0

    @staticmethod
    def _bitrate_to_bps(bitrate: str) -> int:
        """把 "800k" / "2.5m" / "128000" 这类码率字符串换算成 bit/s。"""
        value = bitrate.strip().lower()
        if value.endswith("k"):
            return int(float(value[:-1]) * 1000)
        if value.endswith("m"):
            return int(float(value[:-1]) * 1000 * 1000)
        return int(float(value))

    @classmethod
    def _calculate_maxrate(cls, bitrate: str) -> str:
        """峰值码率 = 目标码率 x1.1: 允许瞬时波动, 又避免 VBR 冲高影响播放。"""
        bps = cls._bitrate_to_bps(bitrate)
        maxrate = int(math.ceil(bps * 1.1))
        return f"{maxrate // 1000}k"

    @classmethod
    def _calculate_bufsize(cls, bitrate: str) -> str:
        """码率缓冲区 = 目标码率 x2: 常规经验值, 太小画质抖动, 太大失去限流作用。"""
        bps = cls._bitrate_to_bps(bitrate)
        bufsize = int(math.ceil(bps * 2))
        return f"{bufsize // 1000}k"

    @staticmethod
    def _validate_input(input_path: Path) -> None:
        """校验输入文件存在、是普通文件、且非空。

        Raises:
            FileNotFoundError: 路径不存在
            ValueError: 不是文件 / 文件大小为 0
        """
        if not input_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {input_path}")
        if not input_path.is_file():
            raise ValueError(f"不是文件: {input_path}")
        if input_path.stat().st_size <= 0:
            raise ValueError(f"视频文件为空: {input_path}")

    @staticmethod
    def _validate_executable(executable: str, name: str) -> None:
        """校验 ffmpeg / ffprobe 可执行文件可用, 让环境问题在构造阶段就暴露。

        两种来源: 显式路径(含目录分隔符)直接检查文件是否存在;
        裸命令名(如 "ffmpeg")则到 PATH 中查找。

        Raises:
            FileNotFoundError: 路径不存在, 或 PATH 中找不到该命令
        """
        path = Path(executable)
        # 用户传绝对/相对路径
        if path.is_absolute() or path.parent != Path("."):
            if not path.exists():
                raise FileNotFoundError(f"{name} 不存在: {executable}")
            return
        # PATH 中查找
        if shutil.which(executable) is None:
            raise FileNotFoundError(
                f"找不到 {name}: {executable}，"
                f"请确保 FFmpeg 已安装并加入 PATH"
            )


# ================================================================
# 测试
# ================================================================
def main(*args, **kwargs) -> None:
    """手工调试入口: 对固定的样例视频跑一次完整转码并打印产物路径。

    输入/输出路径写死在本机目录, 仅用于本地验证转码链路,
    不属于请求调用链; 生产侧应改为由转码服务(任务队列)调用 VideoTranscoder.convert()。
    """
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )
    transcoder = VideoTranscoder(
        threads=4,
        preset="fast",
        segment_time=4,
    )
    input_file = (
        r"D:\Git\fastapi_tuiwen"
        r"\static\medias\videos\202610"
        r"\01a0f53f-1a28-74ed-8caf-5e45add8e941"
        r"\original.mp4"
    )
    output_dir = (
        r"D:\Git\fastapi_tuiwen"
        r"\static\medias\videos\202610"
        r"\01a0f53f-1a28-74ed-8caf-5e45add8e941"
    )
    result = transcoder.convert(
        input_file=input_file,
        output_dir=output_dir,
    )
    print()
    print("======================================")
    print("转码成功")
    print("======================================")
    print("播放列表:")
    print(result.playlist)
    print()
    print("封面:")
    print(result.cover)
    print()
    print("视频:")
    print(result.info.width, "x", result.info.height)
    print()
    print("清晰度:")
    for variant in result.variants:
        print(f"  {variant.name}: {variant.width}x{variant.height} {variant.playlist}")


if __name__ == "__main__":
    main()
