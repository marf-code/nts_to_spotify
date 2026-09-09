-- Spotify Account Data Schema
-- This schema is for loading data from Spotify's account data export

-- User data table
CREATE TABLE IF NOT EXISTS user_data (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255),
    email VARCHAR(255),
    country VARCHAR(10),
    created_from_facebook BOOLEAN,
    facebook_uid VARCHAR(255),
    birthdate DATE,
    gender VARCHAR(50),
    postal_code VARCHAR(20),
    mobile_number VARCHAR(50),
    mobile_operator VARCHAR(100),
    mobile_brand VARCHAR(100),
    creation_time DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Streaming history table (music, podcasts, audiobooks)
CREATE TABLE IF NOT EXISTS streaming_history (
    id SERIAL PRIMARY KEY,
    end_time TIMESTAMP NOT NULL,
    artist_name VARCHAR(500),
    track_name VARCHAR(500),
    ms_played INTEGER NOT NULL,
    content_type VARCHAR(50) DEFAULT 'music', -- music, podcast, audiobook
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for common queries
CREATE INDEX IF NOT EXISTS idx_streaming_history_end_time ON streaming_history(end_time DESC);
CREATE INDEX IF NOT EXISTS idx_streaming_history_artist ON streaming_history(artist_name);
CREATE INDEX IF NOT EXISTS idx_streaming_history_track ON streaming_history(track_name);
CREATE INDEX IF NOT EXISTS idx_streaming_history_content_type ON streaming_history(content_type);

-- Playlists table
CREATE TABLE IF NOT EXISTS playlists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(1000) NOT NULL,
    last_modified_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Playlist items table
CREATE TABLE IF NOT EXISTS playlist_items (
    id SERIAL PRIMARY KEY,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    track_name VARCHAR(500),
    artist_name VARCHAR(500),
    album_name VARCHAR(500),
    track_uri VARCHAR(500),
    item_type VARCHAR(50), -- track, episode, audiobook, local_track
    added_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist_id ON playlist_items(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlist_items_track_uri ON playlist_items(track_uri);

-- Library tracks table
CREATE TABLE IF NOT EXISTS library_tracks (
    id SERIAL PRIMARY KEY,
    artist VARCHAR(500),
    album VARCHAR(500),
    track VARCHAR(500) NOT NULL,
    uri VARCHAR(500) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_library_tracks_uri ON library_tracks(uri);
CREATE INDEX IF NOT EXISTS idx_library_tracks_artist ON library_tracks(artist);

-- Library albums table
CREATE TABLE IF NOT EXISTS library_albums (
    id SERIAL PRIMARY KEY,
    artist VARCHAR(500),
    album VARCHAR(500) NOT NULL,
    uri VARCHAR(500) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Library shows (podcasts) table
CREATE TABLE IF NOT EXISTS library_shows (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    publisher VARCHAR(500),
    uri VARCHAR(500) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Library artists table
CREATE TABLE IF NOT EXISTS library_artists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    uri VARCHAR(500) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Search queries table
CREATE TABLE IF NOT EXISTS search_queries (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(100),
    search_time TIMESTAMP NOT NULL,
    search_query TEXT NOT NULL,
    search_interaction_uris TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_queries_search_time ON search_queries(search_time DESC);
CREATE INDEX IF NOT EXISTS idx_search_queries_platform ON search_queries(platform);

-- Following table (artists, users, etc.)
CREATE TABLE IF NOT EXISTS following (
    id SERIAL PRIMARY KEY,
    uri VARCHAR(500) UNIQUE NOT NULL,
    username VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Inferences table (Spotify's understanding of your preferences)
CREATE TABLE IF NOT EXISTS inferences (
    id SERIAL PRIMARY KEY,
    inference_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payments table
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    payment_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Identity table
CREATE TABLE IF NOT EXISTS identity (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(500),
    first_name VARCHAR(500),
    last_name VARCHAR(500),
    identity_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Identifiers table
CREATE TABLE IF NOT EXISTS identifiers (
    id SERIAL PRIMARY KEY,
    identifier_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Marquee interactions table
CREATE TABLE IF NOT EXISTS marquee_interactions (
    id SERIAL PRIMARY KEY,
    interaction_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wrapped data table (annual Spotify Wrapped)
CREATE TABLE IF NOT EXISTS wrapped_data (
    id SERIAL PRIMARY KEY,
    year INTEGER,
    wrapped_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User prompts table
CREATE TABLE IF NOT EXISTS user_prompts (
    id SERIAL PRIMARY KEY,
    prompt_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sound capsule table
CREATE TABLE IF NOT EXISTS sound_capsule (
    id SERIAL PRIMARY KEY,
    capsule_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Podcast interactions table (rated shows)
CREATE TABLE IF NOT EXISTS podcast_interactions (
    id SERIAL PRIMARY KEY,
    show_name VARCHAR(500) NOT NULL,
    rating INTEGER,
    rated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(show_name, rated_at)
);

CREATE INDEX IF NOT EXISTS idx_podcast_interactions_show ON podcast_interactions(show_name);
CREATE INDEX IF NOT EXISTS idx_podcast_interactions_rating ON podcast_interactions(rating DESC);

-- Extended streaming history table (from Streaming_History_Audio_*.json files)
-- This is the detailed streaming history with full metadata
CREATE TABLE IF NOT EXISTS extended_streaming_history (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    username VARCHAR(255),
    platform VARCHAR(100),
    ms_played INTEGER,
    conn_country VARCHAR(10),
    ip_addr_decrypted VARCHAR(50),
    user_agent_decrypted TEXT,
    master_metadata_track_name VARCHAR(500),
    master_metadata_album_artist_name VARCHAR(500),
    master_metadata_album_album_name VARCHAR(500),
    spotify_track_uri VARCHAR(255),
    episode_name VARCHAR(500),
    episode_show_name VARCHAR(500),
    spotify_episode_uri VARCHAR(255),
    reason_start VARCHAR(100),
    reason_end VARCHAR(100),
    shuffle BOOLEAN,
    skipped BOOLEAN,
    offline BOOLEAN,
    offline_timestamp BIGINT,
    incognito_mode BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts, username, spotify_track_uri, ms_played)
);

-- Indexes for extended streaming history
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_ts ON extended_streaming_history(ts DESC);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_track_uri ON extended_streaming_history(spotify_track_uri);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_track_name ON extended_streaming_history(master_metadata_track_name);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_artist_name ON extended_streaming_history(master_metadata_album_artist_name);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_username ON extended_streaming_history(username);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_country ON extended_streaming_history(conn_country);
CREATE INDEX IF NOT EXISTS idx_extended_streaming_history_platform ON extended_streaming_history(platform);

-- ==============================================================================
-- MATERIALIZED VIEWS - Pre-joined data for better query performance
-- ==============================================================================

-- Materialized view joining streaming history with playlists by URI
-- This creates an efficient "virtual join table" between extended_streaming_history and playlist_items
CREATE MATERIALIZED VIEW IF NOT EXISTS track_playlist_listening AS
SELECT
    esh.spotify_track_uri,
    esh.master_metadata_track_name as track_name,
    esh.master_metadata_album_artist_name as artist_name,
    esh.master_metadata_album_album_name as album_name,
    COUNT(DISTINCT esh.id) as total_plays,
    COUNT(DISTINCT DATE(esh.ts)) as days_played,
    MIN(esh.ts) as first_play,
    MAX(esh.ts) as last_play,
    SUM(esh.ms_played) as total_ms_played,
    COUNT(DISTINCT pi.playlist_id) as in_num_playlists,
    ARRAY_AGG(DISTINCT p.name) FILTER (WHERE p.name IS NOT NULL) as playlist_names
FROM extended_streaming_history esh
LEFT JOIN playlist_items pi ON esh.spotify_track_uri = pi.track_uri
LEFT JOIN playlists p ON pi.playlist_id = p.id
WHERE esh.spotify_track_uri IS NOT NULL
GROUP BY
    esh.spotify_track_uri,
    esh.master_metadata_track_name,
    esh.master_metadata_album_artist_name,
    esh.master_metadata_album_album_name;

-- Indexes on materialized view
CREATE INDEX IF NOT EXISTS idx_track_playlist_listening_uri ON track_playlist_listening(spotify_track_uri);
CREATE INDEX IF NOT EXISTS idx_track_playlist_listening_plays ON track_playlist_listening(total_plays DESC);
CREATE INDEX IF NOT EXISTS idx_track_playlist_listening_artist ON track_playlist_listening(artist_name);

-- Materialized view for playlist listening statistics
CREATE MATERIALIZED VIEW IF NOT EXISTS playlist_listening_stats AS
SELECT
    p.id as playlist_id,
    p.name as playlist_name,
    p.last_modified_date,
    COUNT(DISTINCT pi.id) as total_tracks,
    COUNT(DISTINCT pi.track_uri) as unique_track_uris,
    COUNT(DISTINCT esh.id) as total_plays_from_playlist,
    SUM(esh.ms_played) as total_ms_played,
    ROUND(SUM(esh.ms_played)::numeric / 1000 / 60 / 60, 2) as total_hours,
    COUNT(DISTINCT esh.ts::date) as days_listened,
    MIN(esh.ts) as first_play_from_playlist,
    MAX(esh.ts) as last_play_from_playlist
FROM playlists p
LEFT JOIN playlist_items pi ON p.id = pi.playlist_id
LEFT JOIN extended_streaming_history esh ON pi.track_uri = esh.spotify_track_uri
GROUP BY p.id, p.name, p.last_modified_date;

-- Indexes on playlist stats view
CREATE INDEX IF NOT EXISTS idx_playlist_listening_stats_id ON playlist_listening_stats(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlist_listening_stats_hours ON playlist_listening_stats(total_hours DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_playlist_listening_stats_name ON playlist_listening_stats(playlist_name);
