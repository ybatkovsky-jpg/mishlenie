"""Load parsed books from JSON into the database."""

import asyncio
import json
import sys
from pathlib import Path

from core.database import async_session_factory, create_tables
from core.models import Book, BookSection


async def load_books(json_path: str) -> None:
    """Load books from JSON file into the database."""
    with open(json_path, "r", encoding="utf-8") as f:
        books_data = json.load(f)

    await create_tables()

    async with async_session_factory() as session:
        for book_data in books_data:
            book = Book(
                title=book_data["title"],
                author=book_data.get("author", ""),
                thinking_type=book_data.get("thinking_type", ""),
                format=book_data.get("format", ""),
                total_chars=book_data.get("total_chars", 0),
                section_count=book_data.get("section_count", 0),
            )
            session.add(book)
            await session.flush()  # Get book.id

            for i, section_data in enumerate(book_data.get("sections", [])):
                section = BookSection(
                    book_id=book.id,
                    title=section_data["title"][:512],
                    text=section_data["text"],
                    order_index=i,
                )
                session.add(section)

            print(f"  Loaded: {book.title} ({book.section_count} sections)")

        await session.commit()

    print(f"\nTotal: {len(books_data)} books loaded into database")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "data/books.json"
    asyncio.run(load_books(json_path))
