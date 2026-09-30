# fastapi_tuiwen

# 视频存储方案
```
videos/202609/{video_id}/
  original.mp4                 # 原始文件，用于后续转码
  poster.jpg                   # 封面
  hls/
    playlist.m3u8                # 多码率入口
  hls/360p/
    index.m3u8
    seg_001.ts
    seg_002.ts
  hls/720p/
    index.m3u8
    seg_001.ts
    seg_002.ts
  hls/1080p/
    index.m3u8
    seg_001.ts
    seg_002.ts
```


