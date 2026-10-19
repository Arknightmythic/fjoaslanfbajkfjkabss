import re


def clean_markdown(content: str) -> list[str]:
    """
    Cleansing and chunking markdown content into indexed document pages.
    Supports '<!-- page break -->' separators and tags Q&A with <question> and <answer>.
    """
    pages = content.split("<!-- page break -->")
    cleaned_pages = []

    for page in pages:
        page = page.strip()
        page = re.sub(r"\n{3,}", "\n\n", page)

        # Match Q&A format: Q: ...
        q_match = re.search(r"^Q:\s*(.*?)(?=\n\n|\n<query>|$)", page, flags=re.DOTALL)
        if q_match:
            question = q_match.group(1).strip()
            page_no_q = page[q_match.end():].strip()

            # If no double-newline was present, check if question contains multiple lines
            if not page_no_q and "\n" in question:
                parts = question.split("\n", 1)
                question = parts[0].strip()
                page_no_q = parts[1].strip()

            if "<query>" in page_no_q:
                ans_text, query_text = page_no_q.split("<query>", 1)
                query_text = "<query>" + query_text
            else:
                ans_text = page_no_q
                query_text = ""

            ans_text = ans_text.strip()

            new_page = f"<question>{question}</question>\n"
            if ans_text:
                new_page += f"<answer>{ans_text}</answer>\n"
            if query_text:
                new_page += f"{query_text}"

            page = new_page.strip()

        if page:
            cleaned_pages.append(page)

    return cleaned_pages
