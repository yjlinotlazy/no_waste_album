"""Validated user-owned metadata commands."""

import uuid

from .recipes import normalize


class MetadataService:
    def __init__(self, catalog):
        self.catalog = catalog

    def create_variant(self, asset_id: str, recipe: dict) -> dict:
        if not self.catalog.get(asset_id):
            raise KeyError("asset not found")
        normalized = normalize(recipe)
        normalized["id"] = uuid.uuid4().hex
        return self.catalog.add_variant(asset_id, normalized)

    def delete_variant(self, asset_id: str, variant_id: str) -> None:
        if not self.catalog.delete_variant(asset_id, variant_id):
            raise KeyError("variant not found")
