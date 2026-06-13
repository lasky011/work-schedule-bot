--
-- PostgreSQL database dump
--


-- Dumped from database version 18.3 (Debian 18.3-1.pgdg13+1)
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: shifts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shifts (
    id integer NOT NULL,
    user_id bigint,
    date date NOT NULL,
    hours numeric(4,1) NOT NULL,
    shift_type text,
    is_standard boolean DEFAULT true,
    note text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: shifts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.shifts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: shifts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.shifts_id_seq OWNED BY public.shifts.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    user_id bigint NOT NULL,
    name text,
    notify integer DEFAULT 0,
    notify_time text,
    role text,
    track_hours smallint DEFAULT 0,
    notify_hours smallint DEFAULT 0,
    notify_hours_time text
);


--
-- Name: shifts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shifts ALTER COLUMN id SET DEFAULT nextval('public.shifts_id_seq'::regclass);


--
-- Data for Name: shifts; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.shifts (id, user_id, date, hours, shift_type, is_standard, note, created_at) FROM stdin;
8	655249716	2026-06-01	12.5	morning	t	\N	2026-06-03 09:29:43.961159+00
15	655249716	2026-06-04	15.5	morning	f	\N	2026-06-04 21:28:17.00734+00
16	655249716	2026-06-05	13.5	morning	f	\N	2026-06-05 22:05:49.427544+00


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (user_id, name, notify, notify_time, role, track_hours, notify_hours, notify_hours_time) FROM stdin;
8166505839	Егор Корниенков	0		\N	0	0	\N
1977050773	Екатерина	0		\N	0	0	\N
5211279691	Мария	0		\N	0	0	\N
901759437	Мария	1	00:00	\N	0	0	\N
701683449	Егор Корниенков	0		\N	0	0	\N
943339675	Егор Капустин	0		\N	0	0	\N
655249716	Егор Корниенков	0		Официант	1	1	23:30


--
-- Name: shifts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.shifts_id_seq', 16, true);


--
-- Name: shifts shifts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shifts
    ADD CONSTRAINT shifts_pkey PRIMARY KEY (id);


--
-- Name: shifts shifts_user_id_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shifts
    ADD CONSTRAINT shifts_user_id_date_key UNIQUE (user_id, date);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: shifts shifts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shifts
    ADD CONSTRAINT shifts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- PostgreSQL database dump complete
--


