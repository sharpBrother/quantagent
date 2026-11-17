-- 0012–0016 删表重建了五张表，0011 建在旧表上的 _batch_id 索引随表一起删掉了。
-- 表仍为空，建索引不阻塞写入。
CREATE INDEX "AINDEXVALUATION__batch_id_idx" ON src_wind."AINDEXVALUATION" (_batch_id);
CREATE INDEX "AINDEXMEMBERS__batch_id_idx" ON src_wind."AINDEXMEMBERS" (_batch_id);
CREATE INDEX "SWINDEXMEMBERS__batch_id_idx" ON src_wind."SWINDEXMEMBERS" (_batch_id);
CREATE INDEX "AINDEXINDUSTRIESEODCITICS__batch_id_idx" ON src_wind."AINDEXINDUSTRIESEODCITICS" (_batch_id);
CREATE INDEX "ASHAREDIVIDEND__batch_id_idx" ON src_wind."ASHAREDIVIDEND" (_batch_id);
