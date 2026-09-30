-- One row per entity: radio.track replaces the per-playlist attribute copies in
-- enriched_tracks plus spotify_audio_features and chosic_track_fields; playlist
-- membership moves to radio.playlist / radio.playlist_track.
BEGIN;

-- radio.track ---------------------------------------------------------------

CREATE TABLE radio.track (
    spotify_track_id    text PRIMARY KEY,
    name                text,
    artists             text,
    album               text,
    album_release_date  text,
    isrc                text,
    duration_ms         integer,
    explicit            boolean,
    popularity          integer,
    label               text,
    genres              text[],
    parent_genres       text[],
    tempo               numeric,
    key                 integer,
    mode                integer,
    time_signature      integer,
    energy              numeric,
    danceability        numeric,
    valence             numeric,
    acousticness        numeric,
    instrumentalness    numeric,
    speechiness         numeric,
    liveness            numeric,
    loudness            numeric,
    reccobeats_id       text,
    -- Set once ReccoBeats has been asked; NULL features after that mean it had none.
    features_fetched_at timestamptz,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION pg_temp.split_list(s text) RETURNS text[] LANGUAGE sql IMMUTABLE AS
$$ SELECT array_remove(regexp_split_to_array(trim(s), '\s*,\s*'), '') $$;

-- enriched_tracks key text ("C#/D♭ minor") -> Spotify pitch class and mode.
CREATE FUNCTION pg_temp.pitch_class(k text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
    SELECT array_position(ARRAY['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'],
                          split_part(split_part(replace(k, '♯', '#'), ' ', 1), '/', 1)) - 1
$$;

CREATE FUNCTION pg_temp.mmss_ms(d text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN d ~ '^\d+:\d{2}$'
                THEN (split_part(d, ':', 1)::int * 60 + split_part(d, ':', 2)::int) * 1000 END
$$;

WITH latest AS (
    SELECT DISTINCT ON ("Spotify Track Id") *
    FROM radio.enriched_tracks
    WHERE "Spotify Track Id" <> ''
    ORDER BY "Spotify Track Id", id DESC
), matched AS (
    SELECT DISTINCT ON (spotify_track_id) *
    FROM radio.spotify_tracks
    WHERE found
    ORDER BY spotify_track_id, fetched_at DESC
), ids AS (
    SELECT "Spotify Track Id" AS id FROM latest
    UNION SELECT spotify_track_id FROM matched
    UNION SELECT spotify_track_id FROM radio.spotify_audio_features
    UNION SELECT spotify_track_id FROM radio.chosic_track_fields
)
INSERT INTO radio.track
SELECT
    ids.id,
    coalesce(nullif(e."Song", ''), m.spotify_track_name),
    coalesce(nullif(e."Artist", ''), m.spotify_artists),
    coalesce(nullif(e."Album", ''), m.spotify_album),
    nullif(e."Album Date", ''),
    coalesce(nullif(e."ISRC", ''), m.spotify_isrc, nullif(f.isrc, '')),
    coalesce(pg_temp.mmss_ms(e."Duration"), m.spotify_duration_ms),
    CASE e."Explicit" WHEN 'yes' THEN true WHEN 'no' THEN false END,
    coalesce(c.popularity, e."Popularity", m.spotify_popularity),
    coalesce(c.label, nullif(e."Label", '')),
    pg_temp.split_list(coalesce(c.genres, nullif(e."Genres", ''))),
    pg_temp.split_list(coalesce(c.parent_genres, nullif(e."Parent Genres", ''))),
    coalesce(f.tempo, e."BPM"),
    coalesce(f.key, pg_temp.pitch_class(nullif(e."Key", ''))),
    -- Some exports drop " minor" from Key; the Camelot letter (A = minor) is reliable.
    coalesce(f.mode, CASE WHEN e."Camelot" LIKE '%A' THEN 0 WHEN e."Camelot" LIKE '%B' THEN 1
                          WHEN nullif(e."Key", '') IS NULL THEN NULL
                          WHEN e."Key" LIKE '% minor' THEN 0 ELSE 1 END),
    coalesce(c.time_signature, e."Time Signature"),
    coalesce(f.energy, e."Energy" / 100.0),
    coalesce(f.danceability, e."Dance" / 100.0),
    coalesce(f.valence, e."Valence" / 100.0),
    coalesce(f.acousticness, e."Acoustic" / 100.0),
    coalesce(f.instrumentalness, e."Instrumental" / 100.0),
    coalesce(f.speechiness, e."Speech" / 100.0),
    coalesce(f.liveness, e."Live" / 100.0),
    coalesce(f.loudness, e."Loud (Db)"),
    f.reccobeats_id,
    coalesce(f.fetched_at, CASE WHEN e."Energy" IS NOT NULL THEN now() END),
    now()
FROM ids
LEFT JOIN latest e ON e."Spotify Track Id" = ids.id
LEFT JOIN matched m ON m.spotify_track_id = ids.id
LEFT JOIN radio.spotify_audio_features f ON f.spotify_track_id = ids.id AND f.found
LEFT JOIN radio.chosic_track_fields c ON c.spotify_track_id = ids.id;

-- ReccoBeats misses: remember they were asked so fetch_audio_features.py skips them.
UPDATE radio.track t SET features_fetched_at = f.fetched_at
FROM radio.spotify_audio_features f
WHERE f.spotify_track_id = t.spotify_track_id AND NOT f.found AND t.features_fetched_at IS NULL;

-- radio.playlist / playlist_track -------------------------------------------

CREATE TABLE radio.playlist (
    playlist_id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                text NOT NULL UNIQUE,
    spotify_playlist_id text UNIQUE,
    show_host           text,
    loaded_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE radio.playlist_track (
    playlist_id      integer NOT NULL REFERENCES radio.playlist ON DELETE CASCADE,
    position         integer NOT NULL,
    spotify_track_id text NOT NULL REFERENCES radio.track,
    added_at         date,
    PRIMARY KEY (playlist_id, position)
);
CREATE INDEX playlist_track_track_idx ON radio.playlist_track (spotify_track_id);

-- Carolinasoul rows are an NTS tracklist with no Spotify IDs; radio.nts_tracks already has it.
INSERT INTO radio.playlist (name, show_host)
SELECT "Playlist Name", max(show_host)
FROM radio.enriched_tracks
WHERE "Playlist Name" <> 'Carolinasoul'
GROUP BY 1;

INSERT INTO radio.playlist_track
SELECT p.playlist_id, e."#", e."Spotify Track Id", nullif(e."Added At", '')::date
FROM radio.enriched_tracks e
JOIN radio.playlist p ON p.name = e."Playlist Name";

-- NTS track -> Spotify match cache --------------------------------------------

ALTER TABLE radio.spotify_tracks RENAME TO nts_track_match;
ALTER TABLE radio.nts_track_match RENAME CONSTRAINT spotify_tracks_pkey TO nts_track_match_pkey;
ALTER INDEX radio.spotify_tracks_track_id_idx RENAME TO nts_track_match_track_id_idx;
ALTER TABLE radio.nts_track_match
    DROP COLUMN spotify_track_name,
    DROP COLUMN spotify_artists,
    DROP COLUMN spotify_album,
    DROP COLUMN spotify_isrc,
    DROP COLUMN spotify_popularity,
    DROP COLUMN spotify_duration_ms,
    ADD FOREIGN KEY (spotify_track_id) REFERENCES radio.track;

DROP TABLE radio.enriched_tracks;
DROP TABLE radio.spotify_audio_features;
DROP TABLE radio.chosic_track_fields;

-- NTS shows / episodes / tracks ----------------------------------------------

DROP VIEW radio.nts_episode_genres;

-- Same episode stored under both a percent-encoded and a raw URL; keep the newer row.
DELETE FROM radio.nts_episodes e
USING radio.nts_episodes newer
WHERE newer.show_alias = e.show_alias AND newer.episode_alias = e.episode_alias AND newer.id > e.id;

ALTER TABLE radio.nts_episodes
    DROP COLUMN show_artist,
    ALTER COLUMN genres TYPE text[]
        USING array_remove(regexp_split_to_array(trim(genres), '\s*;\s*'), ''),
    ADD CONSTRAINT nts_episodes_show_alias_episode_alias_key UNIQUE (show_alias, episode_alias);

ALTER TABLE radio.nts_shows DROP COLUMN episodes;

ALTER TABLE radio.nts_tracks
    ADD COLUMN track_key text GENERATED ALWAYS AS (lower(trim(track)) || E'\t' || lower(trim(artist))) STORED,
    ADD FOREIGN KEY (show_alias, episode_alias) REFERENCES radio.nts_episodes (show_alias, episode_alias);
CREATE INDEX nts_tracks_track_key_idx ON radio.nts_tracks (track_key);

-- Wide views -----------------------------------------------------------------

-- Camelot wheel number: major keys step by fifths from C = 8B; a minor key shares its relative major's number.
CREATE FUNCTION radio.camelot(key integer, mode integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN key IS NULL OR mode IS NULL THEN NULL
                WHEN mode = 1 THEN ((7 * key + 7) % 12 + 1) || 'B'
                ELSE ((7 * key + 4) % 12 + 1) || 'A' END
$$;

CREATE VIEW radio.playlist_tracks_wide AS
SELECT p.playlist_id, p.name AS playlist_name, p.spotify_playlist_id, p.show_host,
       pt.position, pt.added_at, t.*, radio.camelot(t.key, t.mode) AS camelot
FROM radio.playlist_track pt
JOIN radio.playlist p USING (playlist_id)
JOIN radio.track t USING (spotify_track_id);

CREATE VIEW radio.nts_tracks_wide AS
SELECT nt.show_alias, nt.episode_alias, nt.position, nt.track, nt.artist,
       nt.offset_seconds, nt.duration_seconds, nt.isrc AS nts_isrc, nt.musicbrainz_track_id, nt.track_key,
       s.name AS show_name, s.artist AS show_host, e.episode_name, e.broadcast,
       e.location AS episode_location, e.genres AS episode_genres,
       m.match_method, m.match_score, t.*, radio.camelot(t.key, t.mode) AS camelot
FROM radio.nts_tracks nt
JOIN radio.nts_episodes e USING (show_alias, episode_alias)
LEFT JOIN radio.nts_shows s USING (show_alias)
LEFT JOIN radio.nts_track_match m ON m.track_key = nt.track_key AND m.found
LEFT JOIN radio.track t ON t.spotify_track_id = m.spotify_track_id;

-- public: Spotify account export ---------------------------------------------

-- The export was loaded three times on 2025-11-19; keep the last load.
DELETE FROM public.playlists WHERE id < (SELECT min(id) FROM public.playlists
                                         WHERE created_at >= '2025-11-19 20:23');
DELETE FROM public.search_queries WHERE created_at < '2025-11-19 20:23';

-- Every row here is also in extended_streaming_history, which has the track URI.
DROP TABLE public.streaming_history;

ALTER TABLE public.extended_streaming_history
    ADD COLUMN spotify_track_id text GENERATED ALWAYS AS (substring(spotify_track_uri FROM '^spotify:track:(.+)$')) STORED;
CREATE INDEX idx_extended_streaming_history_track_id ON public.extended_streaming_history (spotify_track_id);

COMMIT;

REFRESH MATERIALIZED VIEW public.playlist_listening_stats;
REFRESH MATERIALIZED VIEW public.track_playlist_listening;
