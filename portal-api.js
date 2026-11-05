async function savePortalRecord(category, payload) {
    const response = await fetch("/api/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, payload })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Server could not save this record.");
    return result.record;
}

async function fetchPortalRecords(category) {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    const response = await fetch(`/api/records${query}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not load records from server.");
    return result.data;
}
