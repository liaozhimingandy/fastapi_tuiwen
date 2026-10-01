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
    name: str
    short_side: int
    bitrate: str
    audio_bitrate: str = "128k"


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    audio: bool
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    rotation: int = 0

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    @property
    def long_side(self) -> int:
        return max(self.width, self.height)

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def is_square(self) -> bool:
        return self.width == self.height


@dataclass
class HLSVariant:
    name: str
    width: int
    height: int
    bitrate: str
    audio_bitrate: str
    playlist: str


@dataclass
class TranscodeResult:
    playlist: str
    cover: str
    info: VideoInfo
    variants: List[HLSVariant]


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
        return max(2, value - (value % 2))

    @staticmethod
    def _parse_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_fps(value) -> float:
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
        value = bitrate.strip().lower()
        if value.endswith("k"):
            return int(float(value[:-1]) * 1000)
        if value.endswith("m"):
            return int(float(value[:-1]) * 1000 * 1000)
        return int(float(value))

    @classmethod
    def _calculate_maxrate(cls, bitrate: str) -> str:
        bps = cls._bitrate_to_bps(bitrate)
        maxrate = int(math.ceil(bps * 1.1))
        return f"{maxrate // 1000}k"

    @classmethod
    def _calculate_bufsize(cls, bitrate: str) -> str:
        bps = cls._bitrate_to_bps(bitrate)
        bufsize = int(math.ceil(bps * 2))
        return f"{bufsize // 1000}k"

    @staticmethod
    def _validate_input(input_path: Path) -> None:
        if not input_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {input_path}")
        if not input_path.is_file():
            raise ValueError(f"不是文件: {input_path}")
        if input_path.stat().st_size <= 0:
            raise ValueError(f"视频文件为空: {input_path}")

    @staticmethod
    def _validate_executable(executable: str, name: str) -> None:
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
