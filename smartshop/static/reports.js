const inventoryUrl = new URL(window.location.href);
inventoryUrl.searchParams.set('fragment', '1');
const inventoryRows = document.getElementById('inventory-rows');
const inventoryStatus = document.getElementById('inventory-status');

async function refreshInventory() {
    try {
        const response = await fetch(inventoryUrl);
        if (!response.ok || response.redirected) {
            throw new Error('Inventory unavailable');
        }
        inventoryRows.innerHTML = await response.text();
        inventoryStatus.textContent = 'Stock refreshes every five seconds.';
    } catch {
        inventoryStatus.textContent = 'Stock refresh unavailable. Retrying…';
    } finally {
        window.setTimeout(refreshInventory, 5000);
    }
}

window.setTimeout(refreshInventory, 5000);
