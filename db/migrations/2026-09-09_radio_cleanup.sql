BEGIN;
DROP TABLE radio.enriched_tracks_backup;
DROP TABLE radio.tracks;
ALTER TABLE radio.nts_episodes RENAME COLUMN show_name TO episode_name;
ALTER TABLE radio.nts_tracks DROP COLUMN show;
UPDATE radio.enriched_tracks SET "Playlist Name" = show_host WHERE "Playlist Name" IS NULL;
UPDATE radio.enriched_tracks SET show_host = 'Carolinasoul' WHERE "Playlist Name" = 'Carolinasoul';
COMMIT;
