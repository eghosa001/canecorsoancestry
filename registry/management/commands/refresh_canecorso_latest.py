import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand


BASE_URL = "https://www.canecorsopedigree.com/"
PROFILE_URL = urljoin(BASE_URL, "view_dog?id={}")


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dog_id(href):
    if not href:
        return ""
    match = re.search(r"(?:view_pedigree|view_dog)\?id=(\d+)", href)
    return match.group(1) if match else ""


def parse_latest_ids(html):
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        source_id = _dog_id(anchor.get("href"))
        if source_id and source_id not in seen:
            seen.add(source_id)
            ids.append(source_id)
    return ids


def _label_value(soup, label):
    node = soup.find(string=lambda x: _clean(x).rstrip(":") == label if x else False)
    if node is None:
        return ""
    labels = {
        "Name", "Gender", "Father", "Mother", "Dog Parental DNA Confirmed",
        "Picture", "Ped#", "Titles", "Extra titles", "DOB", "Colour", "HD",
        "ED", "Heart", "Date of death", "Other healthscores", "Other",
        "DNA PROFILE", "DSRA Result", "DSRA Result Certified", "DVL2 Result",
        "DVL2 Result Certified", "Inbred percentage", "children",
        "Brothers and sisters",
    }
    values = []
    for element in node.next_elements:
        if element is node:
            continue
        if isinstance(element, str):
            text = _clean(element)
            if not text:
                continue
            if text.rstrip(":") in labels:
                break
            if text.lower() not in {"image", "(click to view pedigree)"}:
                values.append(text)
        elif getattr(element, "name", None) == "a":
            text = _clean(element.get_text(" ", strip=True))
            if text and text.lower() not in {"image"}:
                values.append(text)
    return values[0] if values else ""


def _parent_id_after_label(soup, label):
    node = soup.find(string=lambda x: _clean(x).rstrip(":") == label if x else False)
    if node is None:
        return ""
    for element in node.next_elements:
        if element is node:
            continue
        if isinstance(element, str):
            text = _clean(element).rstrip(":")
            if text and text not in {label, "Image"} and text in {
                "Name", "Gender", "Father", "Mother", "Dog Parental DNA Confirmed",
                "Picture", "Ped#", "Titles", "Extra titles", "DOB", "Colour",
                "HD", "ED", "Heart", "Date of death", "Other healthscores",
                "Other", "DNA PROFILE", "DSRA Result", "DSRA Result Certified",
                "DVL2 Result", "DVL2 Result Certified", "Inbred percentage",
                "children", "Brothers and sisters",
            }:
                break
            continue
        if getattr(element, "name", None) == "a":
            source_id = _dog_id(element.get("href"))
            if source_id:
                return source_id
    return ""


def parse_profile(source_id, html):
    soup = BeautifulSoup(html, "html.parser")
    name = _label_value(soup, "Name")
    if name:
        name = re.sub(
            r"\s*\(click to view pedigree\)\s*$", "", name, flags=re.I
        ).strip()
    return {
        "id": str(source_id),
        "name": name,
        "gender": _label_value(soup, "Gender").lower(),
        "father_id": _parent_id_after_label(soup, "Father"),
        "mother_id": _parent_id_after_label(soup, "Mother"),
        "pedigree_number": _label_value(soup, "Ped#"),
        "dob": _label_value(soup, "DOB"),
        "colour": _label_value(soup, "Colour"),
        "source_url": PROFILE_URL.format(source_id),
    }


class Command(BaseCommand):
    help = "Refresh CaneCorsoPedigree latest additions."

    def handle(self, *args, **options):
        self.stdout.write("No changes.")
