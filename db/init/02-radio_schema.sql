--
-- PostgreSQL database dump
--

\restrict Or3fyvBpmZC2ephfRWGHvexudpFu4LPbzS3U8F9G2bOCIxYO6pkJxvgpjWdQwa4

-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: radio; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA radio;


--
-- Name: camelot(integer, integer); Type: FUNCTION; Schema: radio; Owner: -
--

CREATE FUNCTION radio.camelot(key integer, mode integer) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
    SELECT CASE WHEN key IS NULL OR mode IS NULL THEN NULL
                WHEN mode = 1 THEN ((7 * key + 7) % 12 + 1) || 'B'
                ELSE ((7 * key + 4) % 12 + 1) || 'A' END
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: artist_genres; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.artist_genres (
    artist_key text NOT NULL,
    artist text NOT NULL,
    lastfm_name text,
    lastfm_tags jsonb,
    genres text[],
    found boolean NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nts_episodes; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.nts_episodes (
    id integer NOT NULL,
    show_alias text NOT NULL,
    episode_alias text NOT NULL,
    episode_name text,
    location text,
    broadcast timestamp with time zone,
    genres text[],
    url text NOT NULL
);


--
-- Name: nts_episodes_id_seq; Type: SEQUENCE; Schema: radio; Owner: -
--

CREATE SEQUENCE radio.nts_episodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nts_episodes_id_seq; Type: SEQUENCE OWNED BY; Schema: radio; Owner: -
--

ALTER SEQUENCE radio.nts_episodes_id_seq OWNED BY radio.nts_episodes.id;


--
-- Name: nts_shows; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.nts_shows (
    show_alias text NOT NULL,
    name text,
    artist text,
    location text,
    all_locations text,
    url text NOT NULL
);


--
-- Name: nts_track_match; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.nts_track_match (
    track_key text NOT NULL,
    track text NOT NULL,
    artist text NOT NULL,
    nts_isrc text,
    spotify_track_id text,
    match_method text NOT NULL,
    match_score numeric,
    found boolean NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nts_tracks; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.nts_tracks (
    id integer NOT NULL,
    show_alias text NOT NULL,
    episode_alias text NOT NULL,
    "position" integer NOT NULL,
    track text,
    artist text,
    offset_seconds integer,
    duration_seconds integer,
    isrc text,
    musicbrainz_track_id text,
    track_key text GENERATED ALWAYS AS (((lower(TRIM(BOTH FROM track)) || '	'::text) || lower(TRIM(BOTH FROM artist)))) STORED
);


--
-- Name: nts_tracks_id_seq; Type: SEQUENCE; Schema: radio; Owner: -
--

CREATE SEQUENCE radio.nts_tracks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nts_tracks_id_seq; Type: SEQUENCE OWNED BY; Schema: radio; Owner: -
--

ALTER SEQUENCE radio.nts_tracks_id_seq OWNED BY radio.nts_tracks.id;


--
-- Name: track; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.track (
    spotify_track_id text NOT NULL,
    name text,
    artists text,
    album text,
    album_release_date text,
    isrc text,
    duration_ms integer,
    explicit boolean,
    popularity integer,
    label text,
    genres text[],
    parent_genres text[],
    tempo numeric,
    key integer,
    mode integer,
    time_signature integer,
    energy numeric,
    danceability numeric,
    valence numeric,
    acousticness numeric,
    instrumentalness numeric,
    speechiness numeric,
    liveness numeric,
    loudness numeric,
    reccobeats_id text,
    features_fetched_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nts_tracks_wide; Type: VIEW; Schema: radio; Owner: -
--

CREATE VIEW radio.nts_tracks_wide AS
 SELECT nt.show_alias,
    nt.episode_alias,
    nt."position",
    nt.track,
    nt.artist,
    nt.offset_seconds,
    nt.duration_seconds,
    nt.isrc AS nts_isrc,
    nt.musicbrainz_track_id,
    nt.track_key,
    s.name AS show_name,
    s.artist AS show_host,
    e.episode_name,
    e.broadcast,
    e.location AS episode_location,
    e.genres AS episode_genres,
    m.match_method,
    m.match_score,
    t.spotify_track_id,
    t.name,
    t.artists,
    t.album,
    t.album_release_date,
    t.isrc,
    t.duration_ms,
    t.explicit,
    t.popularity,
    t.label,
    t.genres,
    t.parent_genres,
    t.tempo,
    t.key,
    t.mode,
    t.time_signature,
    t.energy,
    t.danceability,
    t.valence,
    t.acousticness,
    t.instrumentalness,
    t.speechiness,
    t.liveness,
    t.loudness,
    t.reccobeats_id,
    t.features_fetched_at,
    t.updated_at,
    radio.camelot(t.key, t.mode) AS camelot
   FROM ((((radio.nts_tracks nt
     JOIN radio.nts_episodes e USING (show_alias, episode_alias))
     LEFT JOIN radio.nts_shows s USING (show_alias))
     LEFT JOIN radio.nts_track_match m ON (((m.track_key = nt.track_key) AND m.found)))
     LEFT JOIN radio.track t ON ((t.spotify_track_id = m.spotify_track_id)));


--
-- Name: playlist; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.playlist (
    playlist_id integer NOT NULL,
    name text NOT NULL,
    spotify_playlist_id text,
    show_host text,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: playlist_playlist_id_seq; Type: SEQUENCE; Schema: radio; Owner: -
--

ALTER TABLE radio.playlist ALTER COLUMN playlist_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME radio.playlist_playlist_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: playlist_track; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.playlist_track (
    playlist_id integer NOT NULL,
    "position" integer NOT NULL,
    spotify_track_id text NOT NULL,
    added_at date
);


--
-- Name: playlist_tracks_wide; Type: VIEW; Schema: radio; Owner: -
--

CREATE VIEW radio.playlist_tracks_wide AS
 SELECT p.playlist_id,
    p.name AS playlist_name,
    p.spotify_playlist_id,
    p.show_host,
    pt."position",
    pt.added_at,
    t.spotify_track_id,
    t.name,
    t.artists,
    t.album,
    t.album_release_date,
    t.isrc,
    t.duration_ms,
    t.explicit,
    t.popularity,
    t.label,
    t.genres,
    t.parent_genres,
    t.tempo,
    t.key,
    t.mode,
    t.time_signature,
    t.energy,
    t.danceability,
    t.valence,
    t.acousticness,
    t.instrumentalness,
    t.speechiness,
    t.liveness,
    t.loudness,
    t.reccobeats_id,
    t.features_fetched_at,
    t.updated_at,
    radio.camelot(t.key, t.mode) AS camelot
   FROM ((radio.playlist_track pt
     JOIN radio.playlist p USING (playlist_id))
     JOIN radio.track t USING (spotify_track_id));


--
-- Name: nts_episodes id; Type: DEFAULT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes ALTER COLUMN id SET DEFAULT nextval('radio.nts_episodes_id_seq'::regclass);


--
-- Name: nts_tracks id; Type: DEFAULT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_tracks ALTER COLUMN id SET DEFAULT nextval('radio.nts_tracks_id_seq'::regclass);


--
-- Name: artist_genres artist_genres_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.artist_genres
    ADD CONSTRAINT artist_genres_pkey PRIMARY KEY (artist_key);


--
-- Name: nts_episodes nts_episodes_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes
    ADD CONSTRAINT nts_episodes_pkey PRIMARY KEY (id);


--
-- Name: nts_episodes nts_episodes_show_alias_episode_alias_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes
    ADD CONSTRAINT nts_episodes_show_alias_episode_alias_key UNIQUE (show_alias, episode_alias);


--
-- Name: nts_episodes nts_episodes_url_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes
    ADD CONSTRAINT nts_episodes_url_key UNIQUE (url);


--
-- Name: nts_shows nts_shows_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_shows
    ADD CONSTRAINT nts_shows_pkey PRIMARY KEY (show_alias);


--
-- Name: nts_shows nts_shows_url_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_shows
    ADD CONSTRAINT nts_shows_url_key UNIQUE (url);


--
-- Name: nts_track_match nts_track_match_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_track_match
    ADD CONSTRAINT nts_track_match_pkey PRIMARY KEY (track_key);


--
-- Name: nts_tracks nts_tracks_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_tracks
    ADD CONSTRAINT nts_tracks_pkey PRIMARY KEY (id);


--
-- Name: nts_tracks nts_tracks_show_alias_episode_alias_position_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_tracks
    ADD CONSTRAINT nts_tracks_show_alias_episode_alias_position_key UNIQUE (show_alias, episode_alias, "position");


--
-- Name: playlist playlist_name_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist
    ADD CONSTRAINT playlist_name_key UNIQUE (name);


--
-- Name: playlist playlist_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist
    ADD CONSTRAINT playlist_pkey PRIMARY KEY (playlist_id);


--
-- Name: playlist playlist_spotify_playlist_id_key; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist
    ADD CONSTRAINT playlist_spotify_playlist_id_key UNIQUE (spotify_playlist_id);


--
-- Name: playlist_track playlist_track_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist_track
    ADD CONSTRAINT playlist_track_pkey PRIMARY KEY (playlist_id, "position");


--
-- Name: track track_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.track
    ADD CONSTRAINT track_pkey PRIMARY KEY (spotify_track_id);


--
-- Name: nts_episodes_broadcast_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_episodes_broadcast_idx ON radio.nts_episodes USING btree (broadcast);


--
-- Name: nts_episodes_location_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_episodes_location_idx ON radio.nts_episodes USING btree (location);


--
-- Name: nts_episodes_show_alias_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_episodes_show_alias_idx ON radio.nts_episodes USING btree (show_alias);


--
-- Name: nts_shows_location_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_shows_location_idx ON radio.nts_shows USING btree (location);


--
-- Name: nts_track_match_track_id_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_track_match_track_id_idx ON radio.nts_track_match USING btree (spotify_track_id);


--
-- Name: nts_tracks_artist_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_tracks_artist_idx ON radio.nts_tracks USING btree (artist);


--
-- Name: nts_tracks_show_alias_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_tracks_show_alias_idx ON radio.nts_tracks USING btree (show_alias);


--
-- Name: nts_tracks_track_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_tracks_track_idx ON radio.nts_tracks USING btree (track);


--
-- Name: nts_tracks_track_key_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX nts_tracks_track_key_idx ON radio.nts_tracks USING btree (track_key);


--
-- Name: playlist_track_track_idx; Type: INDEX; Schema: radio; Owner: -
--

CREATE INDEX playlist_track_track_idx ON radio.playlist_track USING btree (spotify_track_id);


--
-- Name: nts_track_match nts_track_match_spotify_track_id_fkey; Type: FK CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_track_match
    ADD CONSTRAINT nts_track_match_spotify_track_id_fkey FOREIGN KEY (spotify_track_id) REFERENCES radio.track(spotify_track_id);


--
-- Name: nts_tracks nts_tracks_show_alias_episode_alias_fkey; Type: FK CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_tracks
    ADD CONSTRAINT nts_tracks_show_alias_episode_alias_fkey FOREIGN KEY (show_alias, episode_alias) REFERENCES radio.nts_episodes(show_alias, episode_alias);


--
-- Name: playlist_track playlist_track_playlist_id_fkey; Type: FK CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist_track
    ADD CONSTRAINT playlist_track_playlist_id_fkey FOREIGN KEY (playlist_id) REFERENCES radio.playlist(playlist_id) ON DELETE CASCADE;


--
-- Name: playlist_track playlist_track_spotify_track_id_fkey; Type: FK CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.playlist_track
    ADD CONSTRAINT playlist_track_spotify_track_id_fkey FOREIGN KEY (spotify_track_id) REFERENCES radio.track(spotify_track_id);


--
-- PostgreSQL database dump complete
--

\unrestrict Or3fyvBpmZC2ephfRWGHvexudpFu4LPbzS3U8F9G2bOCIxYO6pkJxvgpjWdQwa4

