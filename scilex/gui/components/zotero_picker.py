"""Choose a Zotero library (yours or a group), then the whole library or a collection.

Used to import a review from Zotero and to set the Zotero library and collection
of an existing review (each review has its own).
"""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import zotero_library
from scilex.gui.services.zotero_library import (
    ZoteroCollection,
    ZoteroLibrary,
    ZoteroSource,
)

WHOLE_LIBRARY = "__library__"


class ZoteroPicker:
    """Library, collection and sub-collection widgets, filled from Zotero on demand."""

    def __init__(self, current: ZoteroSource | None = None, allow_whole_library: bool = True):
        self.current = current
        self.allow_whole_library = allow_whole_library
        self.libraries: dict[str, ZoteroLibrary] = {}
        self.collections: dict[str, ZoteroCollection] = {}
        with ui.column().classes("w-full gap-1") as self.column:
            with ui.row().classes("w-full items-center no-wrap"):
                self.library_select = (
                    ui.select({}, label="Zotero library")
                    .classes("grow")
                    .mark("zotero-library-select")
                )
                ui.button("Load", icon="refresh", on_click=self.load).props(
                    "outline dense no-caps"
                ).mark("zotero-load")
            self.collection_select = (
                ui.select({}, label="Collection", with_input=True)
                .classes("w-full")
                .mark("zotero-collection")
            )
            self.subcollections = ui.checkbox(
                "Include the sub-collections (kept as sub-corpora)", value=True
            ).mark("zotero-subcollections")
        self.library_select.on_value_change(lambda _: self._load_collections())
        if current is not None:
            key = self._library_key(current.library_type, current.library_id)
            self.library_select.set_options(
                {key: current.library_name or f"{current.library_type} {current.library_id}"},
                value=key,
            )
            self.subcollections.value = current.include_subcollections

    @staticmethod
    def _library_key(library_type: str, library_id: str) -> str:
        return f"{library_type}:{library_id}"

    @property
    def library(self) -> ZoteroLibrary | None:
        """The chosen library."""
        return self.libraries.get(self.library_select.value)

    @property
    def collection(self) -> ZoteroCollection | None:
        """The chosen collection (None: the whole library, or nothing chosen)."""
        return self.collections.get(self.collection_select.value)

    async def load(self) -> None:
        """List the libraries the key can read, then the collections of the chosen one."""
        try:
            found = await run.io_bound(zotero_library.list_libraries)
        except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
            show_error("Cannot list the Zotero libraries", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot list the Zotero libraries", exc)
            return
        self.libraries = {
            self._library_key(lib.library_type, lib.library_id): lib for lib in found
        }
        chosen = self.library_select.value if self.library_select.value in self.libraries else None
        self.library_select.set_options(
            {key: lib.name for key, lib in self.libraries.items()},
            value=chosen or next(iter(self.libraries), None),
        )
        await self._load_collections()

    async def _load_collections(self) -> None:
        library = self.library
        if library is None:
            return
        try:
            api = zotero_library.client(library=library)
            found = await run.io_bound(zotero_library.list_collections, api)
        except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
            show_error("Cannot list the Zotero collections", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot list the Zotero collections", exc)
            return
        self.collections = {c.key: c for c in found}
        options = {}
        if self.allow_whole_library:
            options[WHOLE_LIBRARY] = f"Whole library ({library.name})"
        options.update({c.key: f"{c.path} ({c.num_items})" for c in found})
        value = None
        if self.current is not None and self.current.library_id == library.library_id:
            value = self.current.collection_key or (
                WHOLE_LIBRARY if self.allow_whole_library else None
            )
        if value not in options:
            value = None
        self.collection_select.set_options(options, value=value)

    def source(self) -> ZoteroSource | None:
        """The chosen library / collection as a review source (None: incomplete)."""
        library = self.library
        if library is None:
            if self.current is not None and self.collection_select.value is None:
                return self.current  # nothing reloaded: keep the current choice
            return None
        if self.collection_select.value == WHOLE_LIBRARY:
            return ZoteroSource(
                library_id=library.library_id,
                library_type=library.library_type,
                collection_key=None,
                collection_name="",
                include_subcollections=True,
                library_name=library.name,
            )
        collection = self.collection
        if collection is None:
            return None
        return ZoteroSource(
            library_id=library.library_id,
            library_type=library.library_type,
            collection_key=collection.key,
            collection_name=collection.path,
            include_subcollections=bool(self.subcollections.value),
            library_name=library.name,
        )
