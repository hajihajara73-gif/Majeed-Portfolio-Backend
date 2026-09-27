"""
Seed the CMS with the portfolio's current content.

    python -m app.seed

Idempotent: it matches on natural keys (slug, storage_key, label) and updates
rather than inserting duplicates, so it is safe to re-run after editing.

The data here is the same content the public site ships today, which is the
point — it proves the schema actually holds the real thing, and it gives
Phase 6 a like-for-like comparison when the export is wired up.

NOTHING here is invented. Everything came from the repositories, the live
deployments, or the certificates themselves.
"""

from __future__ import annotations

import mimetypes
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.base import utcnow
from app.models.content import (
    AboutContent,
    Achievement,
    CareerEntry,
    EducationEntry,
    ExpertiseItem,
    HomeContent,
    MediaAsset,
    MediaKind,
    MusicSettings,
    MusicTrack,
    Project,
    ProjectHighlight,
    ProjectMedia,
    ProjectTechnology,
    SiteSettings,
    Skill,
    SkillCategory,
    SocialLink,
)

# The frontend's shipped assets, from configuration rather than by counting
# parent directories — that arithmetic pointed outside the repository as soon as
# the layout changed.
PUBLIC_ROOT = get_settings().frontend_public_root

KIND_BY_SUFFIX = {
    ".webp": MediaKind.IMAGE,
    ".jpg": MediaKind.IMAGE,
    ".jpeg": MediaKind.IMAGE,
    ".png": MediaKind.IMAGE,
    ".svg": MediaKind.IMAGE,
    ".mp4": MediaKind.VIDEO,
    ".webm": MediaKind.VIDEO,
    ".mp3": MediaKind.AUDIO,
    ".m4a": MediaKind.AUDIO,
    ".pdf": MediaKind.DOCUMENT,
}


def upsert_media(db: Session, rel_path: str, **fields: Any) -> MediaAsset | None:
    """
    Register a file that already lives under public/.

    Returns None when the file is absent rather than creating a row that points
    at nothing — a media library full of broken references is worse than one
    that is honestly incomplete.
    """
    storage_key = rel_path.lstrip("/")
    disk_path = PUBLIC_ROOT / storage_key
    if not disk_path.is_file():
        print(f"  ! missing, skipped: {storage_key}")
        return None

    existing = db.scalar(
        select(MediaAsset).where(MediaAsset.storage_key == storage_key)
    )
    suffix = disk_path.suffix.lower()
    payload = {
        "kind": KIND_BY_SUFFIX.get(suffix, MediaKind.DOCUMENT),
        "original_filename": disk_path.name,
        "content_type": mimetypes.guess_type(disk_path.name)[0]
        or "application/octet-stream",
        "byte_size": disk_path.stat().st_size,
        **fields,
    }

    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return existing

    asset = MediaAsset(storage_key=storage_key, **payload)
    db.add(asset)
    db.flush()
    return asset


def seed_media(db: Session) -> dict[str, MediaAsset | None]:
    print("media...")
    media: dict[str, MediaAsset | None] = {}

    media["background_video"] = upsert_media(
        db,
        "assets/background/cabin-background.mp4",
        title="Cabin background (seamless loop)",
        folder="backgrounds",
        alt_text=None,
        duration_seconds=7,
        width=848,
        height=478,
    )
    media["background_poster"] = upsert_media(
        db,
        "assets/background/cabin-poster.webp",
        title="Cabin background poster",
        folder="backgrounds",
        alt_text="",
        width=848,
        height=478,
    )
    media["portrait"] = upsert_media(
        db,
        "assets/images/portrait-1024.webp",
        title="Portrait",
        folder="profile",
        alt_text="Mohammed Majeed J",
        width=1024,
        height=1538,
    )
    media["music"] = upsert_media(
        db,
        "assets/audio/placeholder-ambient.mp3",
        title="Ambient placeholder",
        folder="music",
    )

    for slug in ("phd", "zara", "diabetes"):
        media[f"project_{slug}"] = upsert_media(
            db,
            f"assets/projects/{slug}-1280.webp",
            title=f"{slug} screenshot",
            folder="projects",
            alt_text=f"Screenshot of the {slug} project",
            width=1280,
            height=800,
        )
    return media


CERTIFICATES: list[dict[str, Any]] = [
    {
        "slug": "google-technical-support",
        "title": "Technical Support Fundamentals",
        "organization": "Google · Coursera",
        "date_label": "28 December 2023",
        "description": "An online non-credit course authorised by Google and offered through Coursera.",
        "verification_url": "https://coursera.org/verify/5P6T26PGMSK9",
        "is_featured": True,
    },
    {
        "slug": "iit-bombay-intro-to-computers",
        "title": "Introduction to Computers",
        "organization": "Spoken Tutorial Project, IIT Bombay",
        "date_label": "26 August 2023",
        "description": "Training organised at Islamiah College (Autonomous), completed with an online exam conducted remotely from IIT Bombay. Score: 100%.",
        "credential_id": "3317078B6Y",
        "is_featured": True,
    },
    {
        "slug": "isea-cyber-security",
        "title": "Cyber Security",
        "organization": "MeitY · ISEA",
        "date_label": "30 December 2023",
        "description": "Information Security Education and Awareness programme, Ministry of Electronics and Information Technology.",
        "credential_id": "MeitY/ISEA/WCHP/033210",
        "is_featured": True,
    },
    {
        "slug": "simplilearn-data-science-python",
        "title": "Data Science with Python",
        "organization": "Simplilearn",
        "date_label": "29 December 2023",
        "credential_id": "4748011",
        "is_featured": True,
    },
    {
        "slug": "tcs-ion-communication-skills",
        "title": "Communication Skills",
        "organization": "TCS iON",
        "date_label": "19 January 2024",
        "description": "Covering the process of communication, barriers to communication, and verbal and non-verbal communication.",
        "credential_id": "91306-25782095-1016",
    },
    {
        "slug": "infosys-python-basics",
        "title": "Python Basics",
        "organization": "Infosys Springboard",
        "date_label": "30 December 2023",
        "verification_url": "https://verify.onwingspan.com",
    },
    {
        "slug": "infosys-voice-controlled-robot",
        "title": "Voice Controlled Robot",
        "organization": "Infosys Springboard",
        "date_label": "29 December 2023",
        "description": "Experiment 5 — Voice Controlled Robot (Skyrim Kit).",
        "verification_url": "https://verify.onwingspan.com",
    },
    {
        "slug": "chandrayaan-3-mahaquiz",
        "title": "Chandrayaan-3 Mahaquiz",
        "achievement_type": "competition",
        "organization": "MyGov · ISRO",
        "date_label": "2023",
        "description": "Certificate of participation in the national Chandrayaan-3 quiz.",
    },
    {
        "slug": "great-learning-python",
        "title": "Python Programming",
        "organization": "Great Learning Academy",
        "date_label": "July 2023",
    },
    {
        "slug": "mindluster-python",
        "title": "Python",
        "organization": "Mindluster",
        "date_label": "14 October 2023",
        "credential_id": "10788473669",
    },
]


def seed_achievements(db: Session) -> None:
    print("achievements...")
    for order, cert in enumerate(CERTIFICATES, start=1):
        slug = cert["slug"]
        image = upsert_media(
            db,
            f"assets/certificates/{slug}-1200.webp",
            title=cert["title"],
            folder="certificates",
            alt_text=f"{cert['title']} certificate",
        )
        document = upsert_media(
            db,
            f"assets/documents/certificates/{slug}.pdf",
            title=cert["title"],
            folder="certificates",
        )

        row = db.scalar(select(Achievement).where(Achievement.slug == slug))
        if row is None:
            row = Achievement(slug=slug, title=cert["title"])
            db.add(row)

        row.title = cert["title"]
        row.achievement_type = cert.get("achievement_type", "certificate")
        row.organization = cert.get("organization")
        row.date_label = cert.get("date_label")
        row.description = cert.get("description")
        row.credential_id = cert.get("credential_id")
        row.verification_url = cert.get("verification_url")
        row.image_media_id = image.id if image else None
        row.document_media_id = document.id if document else None
        row.is_featured = bool(cert.get("is_featured"))
        row.is_public = True
        row.display_order = order

    # Listed, but its scan and PDF are deliberately NOT published: that document
    # carries a date of birth, register number, photograph and download IP.
    slug = "dote-typewriting-english-junior"
    row = db.scalar(select(Achievement).where(Achievement.slug == slug))
    if row is None:
        row = Achievement(slug=slug)
        db.add(row)
    row.title = "Typewriting English (Junior) — Second Class"
    row.achievement_type = "certificate"
    row.organization = "Government of Tamil Nadu · Directorate of Technical Education"
    row.date_label = "October 2023"
    row.description = "Government Technical Examinations, Board of Examinations, Chennai."
    row.credential_id = "PC / GA23036228"
    row.image_media_id = None
    row.document_media_id = None
    row.allow_download = False
    row.display_order = len(CERTIFICATES) + 1


PROJECTS: list[dict[str, Any]] = [
    {
        "slug": "periyar-phd-admission-system",
        "title": "Periyar University PhD Admission Management System",
        "short_title": "PhD Admission Management System",
        "category": "Full-Stack Web Application",
        "organization": "Periyar University",
        "status": "live",
        "order": 1,
        "featured": True,
        "media": "project_phd",
        "summary": "A comprehensive web-based PhD Admission Management System developed to streamline and digitize the university's research admission workflow. The platform provides structured student and administrative workflows for managing the PhD admission process through dedicated web interfaces.",
        "description": [
            "The system is organised as a monorepo of four independent portals — student, admin, supervisor and research centre — each with its own React frontend and Express API, all sharing a single MySQL database. A separate NestJS service owns queued email delivery."
        ],
        "architecture": "Monorepo with four independent portals, each a React + Vite frontend paired with its own Express API, sharing one MySQL schema. Shared database pooling, mail transport and JWT middleware live in a common module. A standalone NestJS service handles queued email via BullMQ and Redis. Nginx reverse-proxies the modules in production.",
        "live_url": "http://research.periyaruniversity.ac.in/rnd-app/student-app/home",
        "github_url": "https://github.com/majeed74905/project-cdoe",
        "technologies": [
            "React 19", "Vite", "React Router 7", "Bootstrap 5", "Node.js",
            "Express", "MySQL", "NestJS", "Prisma", "JWT", "Argon2", "Redis",
            "BullMQ", "Nodemailer", "Docker", "Nginx",
        ],
        "highlights": [
            "Four separate portals — student, admin, supervisor and research centre — sharing one MySQL database",
            "JWT authentication with per-module secrets, Argon2 password hashing and Redis-backed rate limiting",
            "Versioned SQL migrations covering the admission workflow, eligibility rules and payment handling",
            "Queued transactional email through a dedicated NestJS + BullMQ service",
            "Document uploads, plus generated PDFs, Excel exports and QR codes",
            "Containerised with Docker Compose behind an Nginx reverse proxy",
        ],
    },
    {
        "slug": "zara-ai-platform",
        "title": "Zara AI Platform",
        "short_title": "Zara AI",
        "category": "AI Platform / Full-Stack Web Application",
        "status": "live",
        "order": 2,
        "featured": True,
        "media": "project_zara",
        "summary": "An AI-powered web platform focused on providing an interactive assistant experience through a modern web interface and AI service integrations.",
        "live_url": "https://zara-ai-assists.netlify.app/",
        "github_url": "https://github.com/majeed74905/zara-ai-frontend",
        "technologies": [
            "React 18", "TypeScript", "Vite", "Tailwind CSS", "React Router 6",
            "Framer Motion", "Google Gemini", "Groq", "Monaco Editor",
            "Sandpack", "Google OAuth", "IndexedDB", "Netlify",
        ],
        "highlights": [
            "Integrates two model providers — Google Gemini (@google/genai) and Groq — behind a shared model manager",
            "In-browser code workspace built on Monaco Editor and CodeSandbox Sandpack",
            "Chat, voice, live-session and image modes alongside study tools such as exam prep and flashcards",
            "Diagram rendering through Graphviz (viz.js)",
            "Google OAuth sign-in with local persistence via IndexedDB for offline use",
        ],
    },
    {
        "slug": "diabetes-prediction",
        "title": "Diabetes Prediction",
        "short_title": "Diabetes Prediction",
        "category": "Machine Learning",
        "status": "live",
        "order": 3,
        "featured": True,
        "media": "project_diabetes",
        "summary": "A machine-learning based web application that predicts the likelihood of diabetes using user-provided input parameters. The project demonstrates the integration of a trained machine-learning workflow with a web-accessible prediction interface.",
        "live_url": "https://diabetic-prediction-y2qs.onrender.com/",
        "github_url": "https://github.com/majeed74905/diabetic-prediction",
        "technologies": [
            "Python 3.11", "Flask", "scikit-learn", "Logistic Regression",
            "pandas", "NumPy", "joblib", "Gunicorn", "Render",
        ],
        "highlights": [
            "Logistic Regression classifier trained with scikit-learn",
            "StandardScaler feature scaling, with model and scaler persisted via joblib",
            "Eight clinical inputs, including glucose, BMI, insulin and diabetes pedigree function",
            "Separate preprocessing, training and prediction modules, plus an EDA notebook",
            "Deployed on Render under Gunicorn with a health-check endpoint",
        ],
    },
    {
        "slug": "online-library-management-system",
        "title": "Online Library Management System",
        "short_title": "Library Management System",
        "category": "Web Application",
        "status": "local",
        "deployment_note": "Local deployment",
        "order": 4,
        "featured": False,
        "media": None,
        "summary": "An online library management system developed to digitize core library operations, including the management of library records and common CRUD-based workflows through a web interface.",
        "github_url": "https://github.com/majeed74905/online-library-management-system",
        "technologies": ["PHP", "PDO", "MySQL", "Bootstrap", "jQuery", "DataTables"],
        "highlights": [
            "Separate administrator and student areas with session-based login",
            "CRUD management for books, authors and categories",
            "Student registration, book issue and return tracking with borrowing history",
            "Database access through PDO prepared statements against MySQL",
        ],
    },
]


def seed_projects(db: Session, media: dict[str, MediaAsset | None]) -> None:
    print("projects...")
    for spec in PROJECTS:
        row = db.scalar(select(Project).where(Project.slug == spec["slug"]))
        if row is None:
            row = Project(slug=spec["slug"], title=spec["title"])
            db.add(row)

        row.title = spec["title"]
        row.short_title = spec.get("short_title")
        row.category = spec.get("category")
        row.organization = spec.get("organization")
        row.status = spec["status"]
        row.deployment_note = spec.get("deployment_note")
        row.summary = spec.get("summary")
        row.description = spec.get("description")
        row.architecture = spec.get("architecture")
        row.github_url = spec.get("github_url")
        row.live_url = spec.get("live_url")
        row.is_featured = spec["featured"]
        row.is_published = True
        row.display_order = spec["order"]

        cover = media.get(spec["media"]) if spec.get("media") else None
        row.cover_media_id = cover.id if cover else None
        # Now that every NOT NULL column is set, it is safe to flush and get
        # the id the child rows need.
        db.flush()

        # Replace the child rows wholesale — simpler than diffing, and these
        # lists are small.
        for child in list(row.technologies):
            db.delete(child)
        for child in list(row.highlights):
            db.delete(child)
        for child in list(row.gallery):
            db.delete(child)
        db.flush()

        for i, tech in enumerate(spec["technologies"]):
            db.add(
                ProjectTechnology(project_id=row.id, name=tech, display_order=i)
            )
        for i, text_ in enumerate(spec["highlights"]):
            db.add(
                ProjectHighlight(project_id=row.id, text=text_, display_order=i)
            )
        if cover:
            db.add(
                ProjectMedia(
                    project_id=row.id, media_id=cover.id, display_order=0
                )
            )


SKILLS: list[tuple[str, str, str, list[str]]] = [
    ("programming", "Languages", "The languages I write day to day.",
     ["Python", "JavaScript", "TypeScript"]),
    ("frontend", "Frontend", "Interfaces, build tooling and styling.",
     ["React", "Vite", "Tailwind CSS"]),
    ("backend", "Backend", "APIs and server-side services.",
     ["FastAPI", "Node.js", "Express"]),
    ("database", "Data", "Storage, schema design and access layers.",
     ["PostgreSQL", "MySQL", "Prisma"]),
    ("ai-ml", "AI / ML", "Model providers and tooling I have built against.",
     ["OpenAI", "Google Gemini", "Anthropic Claude", "Groq", "DeepSeek",
      "Hugging Face"]),
    ("tools-cloud", "Cloud & Tools", "Where the work gets deployed and run.",
     ["AWS", "Netlify", "Railway", "Render"]),
]


def seed_skills(db: Session) -> None:
    print("skills...")
    for order, (slug, label, summary, names) in enumerate(SKILLS):
        category = db.scalar(
            select(SkillCategory).where(SkillCategory.slug == slug)
        )
        if category is None:
            category = SkillCategory(slug=slug, label=label)
            db.add(category)
        category.label = label
        category.summary = summary
        category.display_order = order
        # Flush only once every NOT NULL column is populated — flushing on
        # construction fires the INSERT with nulls still in place.
        db.flush()

        for child in list(category.skills):
            db.delete(child)
        db.flush()
        for i, name in enumerate(names):
            # proficiency deliberately left NULL — the site shows no bars.
            db.add(Skill(category_id=category.id, name=name, display_order=i))


def seed_singletons(db: Session, media: dict[str, MediaAsset | None]) -> None:
    print("site / home / about / music settings...")

    site = db.get(SiteSettings, 1) or SiteSettings(id=1)
    site.name = "Mohammed Majeed J"
    site.short_name = "Mohammed Majeed"
    site.monogram = "MJ"
    site.locale = "en"
    site.seo_title = "Mohammed Majeed J — Full Stack Developer"
    site.seo_description = (
        "Full stack developer working across Python backends, React interfaces "
        "and applied AI. Selected projects, skills and background."
    )
    site.contact_email = "majeed74905@gmail.com"
    site.contact_phone = "+91 93619 71840"
    site.footer_note = "Designed and built by Mohammed Majeed J."
    site.maintenance_mode = False
    db.add(site)

    home = db.get(HomeContent, 1) or HomeContent(id=1)
    home.greeting = "Welcome"
    home.headline = "I build systems that hold together."
    home.introduction = (
        "I work across the whole stack — Python and FastAPI services, React "
        "interfaces, and the data and AI layers in between. This is a selection "
        "of what I have built and how I approach the work."
    )
    home.roles = [
        "Full Stack Developer",
        "Python Backend Specialist",
        "AI Enthusiast",
    ]
    home.technology_highlights = [
        "React", "TypeScript", "Python", "FastAPI", "Node.js", "PostgreSQL",
        "Tailwind CSS",
    ]
    home.notes_label = "Field notes"
    home.notes_lines = []
    home.primary_cta_label = "View Projects"
    home.primary_cta_href = "#projects"
    video = media.get("background_video")
    poster = media.get("background_poster")
    home.background_video_id = video.id if video else None
    home.background_poster_id = poster.id if poster else None
    db.add(home)

    about = db.get(AboutContent, 1) or AboutContent(id=1)
    about.introduction = (
        "I am a full stack developer focused on backend engineering with "
        "Python and applied AI."
    )
    about.biography = [
        "I am an MCA student at Periyar University, and most of what I know came from building things other people then had to use. The largest of those is the university's own PhD admission platform — four separate portals over one MySQL database — which now runs in production for its research admissions.",
        "The rest of my work spans the stack rather than one corner of it: a React and TypeScript AI workspace built against Gemini and Groq, a scikit-learn classifier served through Flask, and a PHP records system from my undergraduate final year. Different languages, the same habit — get the data model right first, then make the interface honest about it.",
    ]
    about.interests = [
        "AI and machine learning",
        "Scalable backend systems",
        "Cloud infrastructure",
        "Cybersecurity",
    ]
    about.facts = [
        {"label": "Studying", "value": "MCA · Periyar University"},
        {"label": "Projects shipped", "value": "4"},
        {"label": "Publicly deployed", "value": "3"},
        {"label": "In production", "value": "Periyar University"},
    ]
    portrait = media.get("portrait")
    about.portrait_media_id = portrait.id if portrait else None
    db.add(about)

    music_settings = db.get(MusicSettings, 1) or MusicSettings(id=1)
    music_settings.is_enabled = True
    music_settings.autoplay = False
    music_settings.default_volume = 40
    music_settings.loop = True
    music_settings.position = "footer"
    db.add(music_settings)


def seed_lists(db: Session, media: dict[str, MediaAsset | None]) -> None:
    print("education / expertise / career / social / music...")

    education = [
        ("Master of Computer Applications (MCA)", "Periyar University"),
        ("Bachelor of Computer Applications (BCA)", "Islamiah College (Autonomous)"),
    ]
    for order, (degree, institution) in enumerate(education):
        row = db.scalar(
            select(EducationEntry).where(
                EducationEntry.degree == degree,
                EducationEntry.institution == institution,
            )
        )
        if row is None:
            row = EducationEntry(degree=degree, institution=institution)
            db.add(row)
        # Dates intentionally left null — they have never been supplied, and a
        # guessed year on an education record is not a harmless placeholder.
        row.display_order = order

    expertise = [
        ("Full Stack Development",
         "React and TypeScript interfaces backed by APIs I also build."),
        ("Python Backend Engineering",
         "FastAPI services, relational data modelling, and API design."),
        ("Applied AI",
         "Building on top of hosted model APIs and integrating them into products."),
        ("Cloud & Deployment",
         "Shipping and running applications on managed cloud platforms."),
    ]
    for order, (title, summary) in enumerate(expertise):
        row = db.scalar(select(ExpertiseItem).where(ExpertiseItem.title == title))
        if row is None:
            row = ExpertiseItem(title=title)
            db.add(row)
        row.summary = summary
        row.display_order = order

    career = [
        ("Master of Computer Applications", "Periyar University"),
        ("Bachelor of Computer Applications", "Islamiah College (Autonomous)"),
    ]
    for order, (title, organization) in enumerate(career):
        row = db.scalar(
            select(CareerEntry).where(
                CareerEntry.title == title,
                CareerEntry.organization == organization,
            )
        )
        if row is None:
            row = CareerEntry(title=title, organization=organization)
            db.add(row)
        row.entry_type = "education"
        row.display_order = order

    social = [
        ("GitHub", "https://github.com/majeed74905"),
        ("LinkedIn", "https://www.linkedin.com/in/mohammed-majeed-a337842a4"),
        ("Instagram", "https://www.instagram.com/md_afzal_3237/"),
        ("Email", "mailto:majeed74905@gmail.com"),
    ]
    for order, (label, href) in enumerate(social):
        row = db.scalar(select(SocialLink).where(SocialLink.label == label))
        if row is None:
            row = SocialLink(label=label)
            db.add(row)
        row.href = href
        row.is_external = True
        row.display_order = order

    audio = media.get("music")
    track = db.scalar(
        select(MusicTrack).where(MusicTrack.title == "Ambient placeholder")
    )
    if track is None:
        track = MusicTrack(title="Ambient placeholder")
        db.add(track)
    track.artist = "Temporary — replace before launch"
    track.audio_media_id = audio.id if audio else None
    track.is_placeholder = True
    track.is_featured = True
    track.is_enabled = True
    track.display_order = 0


def main() -> int:
    with SessionLocal() as db:
        media = seed_media(db)
        db.flush()
        seed_singletons(db, media)
        seed_lists(db, media)
        seed_skills(db)
        seed_projects(db, media)
        seed_achievements(db)
        db.commit()
    print(f"\nseeded at {utcnow().isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
