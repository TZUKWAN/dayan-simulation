"""Evidence roles describe the retrieved artifact, not the connector's name."""

CATALOG = {"huggingface_datasets", "ckan_search"}


def artifact_role(connector, records, meta=None):
    if (meta or {}).get("artifact_role"):
        return meta["artifact_role"]
    if connector in CATALOG:
        return "catalog_only"
    if connector in ("crossref", "openalex"):
        return "bibliographic_metadata"
    if connector == "web_page":
        if any(r.get("type") in ("numeric_stat", "topic_stat") for r in records):
            return "text_evidence"  # still requires extraction/definition checks before numerical binding
        return "catalog_only"  # navigation/portal text does not prove a statistical table download
    if connector == "gdelt_doc":
        return "article_metadata"
    return "dataset" if records else "empty"


def usable_task(task):
    return task.get("status") == "done" and task.get("n_records", 0) > 0 and task.get("artifact_role") != "empty"
