-- ============================================================================
-- 001_rename_columns.sql —— 存量库升级脚本(对应模型层字段改名那一轮改动)
--
-- 适用范围: 已经有数据、且表结构停留在「改名之前」的 PostgreSQL 库。
--           全新库不需要执行 —— 直接启动服务由 SQLModel.metadata.create_all 建表即可。
--
-- 覆盖内容:
--   1. 列改名   create_at → created_at / update_at → updated_at / nick_name → nickname /
--              gmt_birth → birthday / obj_id → target_id / obj_type → target_type /
--              snap.like → snap.like_count / notice.type → notice_type /
--              video_source.type → source_type
--   2. 索引改名 与上面的列改名保持一致, 避免留下 idx_obj_type_obj_id 这种误导性名字
--   3. 列宽扩展 file.url / video_source.url 128 → 255(装不下 HLS 相对路径)
--   4. 数据归一 video_source.quality 由 "360"/"720"/"1080" 统一成 "360p"/"720p"/"1080p"
--
-- 用法:
--   psql -h <host> -U <user> -d <db> -v ON_ERROR_STOP=1 -f migrations/001_rename_columns.sql
--
-- 特性: 幂等。整段包在一个事务里, 每一步都先探测再执行, 重复跑不会报错。
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. 列改名
--    用 DO 块逐条探测(ALTER TABLE ... RENAME COLUMN 不支持 IF EXISTS),
--    既处理「老名还在」也处理「已经改过一次」的情况。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            -- 账户表
            ('tw_account',      'create_at', 'created_at'),
            ('tw_account',      'update_at', 'updated_at'),
            ('tw_account',      'nick_name', 'nickname'),
            ('tw_account',      'gmt_birth', 'birthday'),
            -- 帖子
            ('tw_post',         'create_at', 'created_at'),
            ('tw_post',         'update_at', 'updated_at'),
            -- 评论
            ('tw_comment',      'create_at', 'created_at'),
            ('tw_comment',      'obj_id',    'target_id'),
            ('tw_comment',      'obj_type',  'target_type'),
            -- 点赞
            ('tw_like',         'create_at', 'created_at'),
            ('tw_like',         'obj_id',    'target_id'),
            ('tw_like',         'obj_type',  'target_type'),
            -- 关注
            ('tw_follow',       'create_at', 'created_at'),
            -- 文件
            ('tw_file',         'create_at', 'created_at'),
            -- 用户反馈
            ('tw_feedback',     'create_at', 'created_at'),
            ('tw_feedback',     'update_at', 'updated_at'),
            -- 通知(`type` 与内置名/SQL 保留字冲突)
            ('tw_notice',       'create_at', 'created_at'),
            ('tw_notice',       'update_at', 'updated_at'),
            ('tw_notice',       'type',      'notice_type'),
            -- 天亮即焚(`like` 与 LIKE 运算符冲突)
            ('tw_snap',         'create_at', 'created_at'),
            ('tw_snap',         'like',      'like_count'),
            -- 视频
            ('tw_video',        'create_at', 'created_at'),
            ('tw_video',        'update_at', 'updated_at'),
            -- 视频源(`type` 与内置名/SQL 保留字冲突)
            ('tw_video_source', 'create_at', 'created_at'),
            ('tw_video_source', 'type',      'source_type')
        ) AS t(tbl, old_col, new_col)
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema()
                     AND table_name = r.tbl AND column_name = r.old_col)
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema()
                     AND table_name = r.tbl AND column_name = r.new_col)
        THEN
            EXECUTE format('ALTER TABLE %I RENAME COLUMN %I TO %I', r.tbl, r.old_col, r.new_col);
            RAISE NOTICE 'rename column %.% -> %', r.tbl, r.old_col, r.new_col;
        END IF;
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 2. 索引 / 唯一约束改名
--    RENAME COLUMN 不会连带改索引名: 索引仍能正常用, 但名字停留在旧列名上,
--    排查慢查询时容易误判。这里把它们对齐。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('idx_obj_type_obj_id_account_id_unique', 'idx_target_type_target_id_account_id_unique'),
            ('idx_obj_type_obj_id',                   'idx_target_type_target_id')
        ) AS t(old_name, new_name)
    LOOP
        IF EXISTS (SELECT 1 FROM pg_indexes
                   WHERE schemaname = current_schema() AND indexname = r.old_name)
           AND NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE schemaname = current_schema() AND indexname = r.new_name)
        THEN
            EXECUTE format('ALTER INDEX %I RENAME TO %I', r.old_name, r.new_name);
            RAISE NOTICE 'rename index % -> %', r.old_name, r.new_name;
        END IF;
    END LOOP;

    -- 唯一约束名里的 video_type 也是旧列名, 一并纠正
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'uq_video_source_video_type_quality'
                 AND conrelid = 'tw_video_source'::regclass)
       AND NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'uq_video_source_video_source_type_quality'
                         AND conrelid = 'tw_video_source'::regclass)
    THEN
        ALTER TABLE tw_video_source
            RENAME CONSTRAINT uq_video_source_video_type_quality
                          TO uq_video_source_video_source_type_quality;
        RAISE NOTICE 'rename constraint uq_video_source_video_type_quality';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. 列宽扩展
--    file.url / video_source.url 原来是 VARCHAR(128), 存 HLS 相对路径
--    (videos/<md5>/1080p/index.m3u8) 或长 CDN 域名时会超长。加宽不丢数据。
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS tw_file         ALTER COLUMN url TYPE VARCHAR(255);
ALTER TABLE IF EXISTS tw_video_source ALTER COLUMN url TYPE VARCHAR(255);

-- ---------------------------------------------------------------------------
-- 4. 数据归一: 清晰度枚举取值从 "360"/"720"/"1080" 改成带 p 的 "360p"/"480p"/...
--    不改的话, 这些老行读出来不是 VideoQuality 枚举成员。
-- ---------------------------------------------------------------------------
UPDATE tw_video_source SET quality = quality || 'p'
 WHERE quality IN ('360', '480', '720', '1080');

COMMIT;

-- ---------------------------------------------------------------------------
-- 附: 本次改动顺带收敛了几处「可空却必填 / 布尔列注释写反」的问题, 属于应用层
--     约束, 不动表结构, 因此上面没有对应语句。若要把 feedback.updated_at 之类的
--     老数据补上, 先跑:
--         SELECT count(*) FROM tw_feedback WHERE updated_at IS NULL;
--     确认数量后再决定 UPDATE 还是 SET NOT NULL。
-- ---------------------------------------------------------------------------
