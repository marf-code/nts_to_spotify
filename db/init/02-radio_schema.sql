--
-- PostgreSQL database dump
--

\restrict x75YR07Ntp0k1G0d2oaUS0p2z4UDODK0wEsePMgd8UVSasth7BQKdobLucDWfjT

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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: enriched_tracks; Type: TABLE; Schema: radio; Owner: -
--

CREATE TABLE radio.enriched_tracks (
    id integer NOT NULL,
    "#" integer,
    "Song" text,
    "Artist" text,
    "BPM" numeric,
    "Camelot" text,
    "Energy" integer,
    "Added At" text,
    "Duration" text,
    "Popularity" integer,
    "Genres" text,
    "Parent Genres" text,
    "Album" text,
    "Album Date" text,
    "Dance" integer,
    "Acoustic" integer,
    "Instrumental" integer,
    "Valence" integer,
    "Speech" integer,
    "Live" integer,
    "Loud (Db)" numeric,
    "Key" text,
    "Time Signature" integer,
    "Spotify Track Id" text,
    "Label" text,
    "ISRC" text,
    "Explicit" text,
    "Playlist Name" text,
    show_host text
);


--
-- Name: enriched_tracks_id_seq; Type: SEQUENCE; Schema: radio; Owner: -
--

ALTER TABLE radio.enriched_tracks ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME radio.enriched_tracks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
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
    genres text,
    show_artist text,
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
    episodes integer,
    url text NOT NULL
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
    musicbrainz_track_id text
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
-- Name: nts_episodes id; Type: DEFAULT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes ALTER COLUMN id SET DEFAULT nextval('radio.nts_episodes_id_seq'::regclass);


--
-- Name: nts_tracks id; Type: DEFAULT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_tracks ALTER COLUMN id SET DEFAULT nextval('radio.nts_tracks_id_seq'::regclass);


--
-- Name: enriched_tracks enriched_tracks_pkey1; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.enriched_tracks
    ADD CONSTRAINT enriched_tracks_pkey1 PRIMARY KEY (id);


--
-- Name: nts_episodes nts_episodes_pkey; Type: CONSTRAINT; Schema: radio; Owner: -
--

ALTER TABLE ONLY radio.nts_episodes
    ADD CONSTRAINT nts_episodes_pkey PRIMARY KEY (id);


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
-- PostgreSQL database dump complete
--

\unrestrict x75YR07Ntp0k1G0d2oaUS0p2z4UDODK0wEsePMgd8UVSasth7BQKdobLucDWfjT

