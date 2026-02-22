-- ============================================================
-- AgentFlow Supabase Schema
-- Run this in the Supabase SQL Editor to set up all tables.
-- ============================================================

-- Enable pgvector extension
create extension if not exists vector with schema extensions;

-- ────────────────────────────────────────────
-- BLOCKS
-- ────────────────────────────────────────────
create table if not exists blocks (
    id             text primary key,
    name           text not null,
    description    text not null default '',
    category       text not null default 'process',
    execution_type text not null default 'llm',
    input_schema   jsonb not null default '{}',
    output_schema  jsonb not null default '{}',
    prompt_template text,
    source_code    text,
    use_when       text,
    tags           text[] not null default '{}',
    examples       jsonb not null default '[]',
    metadata       jsonb not null default '{}',
    search_vector  tsvector,
    embedding      vector(1536),
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create index if not exists blocks_search_idx on blocks using gin(search_vector);
create index if not exists blocks_embedding_idx on blocks using hnsw(embedding vector_cosine_ops);

-- Trigger to keep search_vector in sync
create or replace function blocks_search_vector_update() returns trigger as $$
begin
    new.search_vector :=
        setweight(to_tsvector('english', coalesce(new.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(new.description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(new.use_when, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(array_to_string(new.tags, ' '), '')), 'C');
    return new;
end;
$$ language plpgsql;

drop trigger if exists blocks_search_vector_trigger on blocks;
create trigger blocks_search_vector_trigger
    before insert or update on blocks
    for each row execute function blocks_search_vector_update();

-- ────────────────────────────────────────────
-- PIPELINES
-- ────────────────────────────────────────────
create table if not exists pipelines (
    id             text primary key,
    name           text not null default 'Untitled',
    user_prompt    text not null default '',
    user_id        text not null default 'default_user',
    nodes          jsonb not null default '[]',
    edges          jsonb not null default '[]',
    memory_keys    text[] not null default '{}',
    status         text not null default 'created',
    trigger_type   text not null default 'manual',
    trigger        jsonb not null default '{}',
    webhook_path   text,
    node_count     int not null default 0,
    search_vector  tsvector,
    embedding      vector(1536),
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create index if not exists pipelines_search_idx on pipelines using gin(search_vector);
create index if not exists pipelines_user_idx on pipelines(user_id);
create index if not exists pipelines_webhook_idx on pipelines(webhook_path);

-- Trigger to keep search_vector in sync
create or replace function pipelines_search_vector_update() returns trigger as $$
begin
    new.search_vector :=
        setweight(to_tsvector('english', coalesce(new.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(new.user_prompt, '')), 'B');
    return new;
end;
$$ language plpgsql;

drop trigger if exists pipelines_search_vector_trigger on pipelines;
create trigger pipelines_search_vector_trigger
    before insert or update on pipelines
    for each row execute function pipelines_search_vector_update();

-- ────────────────────────────────────────────
-- EXECUTIONS
-- ────────────────────────────────────────────
create table if not exists executions (
    run_id          text primary key,
    pipeline_id     text references pipelines(id) on delete set null,
    pipeline_name   text not null default '',
    pipeline_intent text not null default '',
    user_id         text not null default 'default_user',
    status          text not null default 'running',
    node_count      int not null default 0,
    node_results    jsonb not null default '[]',
    shared_context  jsonb not null default '{}',
    errors          jsonb not null default '[]',
    started_at      timestamptz not null default now(),
    finished_at     timestamptz
);

create index if not exists executions_pipeline_idx on executions(pipeline_id);
create index if not exists executions_user_idx on executions(user_id);
create index if not exists executions_finished_idx on executions(finished_at desc);

-- ────────────────────────────────────────────
-- USER MEMORY
-- ────────────────────────────────────────────
create table if not exists user_memory (
    user_id    text not null,
    key        text not null,
    value      jsonb not null default 'null',
    updated_at timestamptz not null default now(),
    primary key (user_id, key)
);

-- ────────────────────────────────────────────
-- NOTIFICATIONS
-- ────────────────────────────────────────────
create table if not exists notifications (
    id         bigint generated always as identity primary key,
    user_id    text not null default 'default_user',
    pipeline_id text,
    run_id     text,
    node_id    text,
    title      text not null,
    message    text not null default '',
    level      text not null default 'info',
    category   text not null default 'notification',
    read       boolean not null default false,
    metadata   jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists notifications_user_idx on notifications(user_id, created_at desc);

-- ────────────────────────────────────────────
-- CHAT SESSIONS
-- ────────────────────────────────────────────
create table if not exists chat_sessions (
    id         text primary key,
    history    jsonb not null default '[]',
    status     text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ────────────────────────────────────────────
-- RPC: hybrid search for blocks
-- ────────────────────────────────────────────
create or replace function search_blocks(
    query_text text,
    query_embedding vector(1536) default null,
    match_limit int default 10,
    full_text_weight float default 1.0,
    semantic_weight float default 1.0
)
returns table (
    id text,
    name text,
    description text,
    category text,
    execution_type text,
    input_schema jsonb,
    output_schema jsonb,
    prompt_template text,
    source_code text,
    use_when text,
    tags text[],
    examples jsonb,
    metadata jsonb,
    score float
)
language plpgsql
as $$
begin
    return query
    select
        b.id,
        b.name,
        b.description,
        b.category,
        b.execution_type,
        b.input_schema,
        b.output_schema,
        b.prompt_template,
        b.source_code,
        b.use_when,
        b.tags,
        b.examples,
        b.metadata,
        (
            coalesce(full_text_weight * ts_rank(b.search_vector, plainto_tsquery('english', query_text)), 0) +
            case
                when query_embedding is not null and b.embedding is not null
                then semantic_weight * (1 - (b.embedding <=> query_embedding))
                else 0
            end
        )::float as score
    from blocks b
    where
        b.search_vector @@ plainto_tsquery('english', query_text)
        or (query_embedding is not null and b.embedding is not null and (b.embedding <=> query_embedding) < 0.7)
    order by score desc
    limit match_limit;
end;
$$;

-- ────────────────────────────────────────────
-- RPC: hybrid search for pipelines
-- ────────────────────────────────────────────
create or replace function search_pipelines(
    query_text text,
    query_embedding vector(1536) default null,
    match_limit int default 10
)
returns table (
    id text,
    name text,
    user_prompt text,
    user_id text,
    status text,
    node_count int,
    created_at timestamptz,
    score float
)
language plpgsql
as $$
begin
    return query
    select
        p.id,
        p.name,
        p.user_prompt,
        p.user_id,
        p.status,
        p.node_count,
        p.created_at,
        (
            coalesce(ts_rank(p.search_vector, websearch_to_tsquery('english', query_text)), 0) +
            case
                when query_embedding is not null and p.embedding is not null
                then (1 - (p.embedding <=> query_embedding))
                else 0
            end
        )::float as score
    from pipelines p
    where
        p.search_vector @@ websearch_to_tsquery('english', query_text)
        or (query_embedding is not null and p.embedding is not null and (p.embedding <=> query_embedding) < 0.5)
    order by score desc
    limit match_limit;
end;
$$;

-- ────────────────────────────────────────────
-- Updated_at trigger
-- ────────────────────────────────────────────
create or replace function update_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create or replace trigger blocks_updated_at
    before update on blocks
    for each row execute function update_updated_at();

create or replace trigger pipelines_updated_at
    before update on pipelines
    for each row execute function update_updated_at();
