"""Spreadsheet-compatible downloads for the report views."""
import csv
from io import StringIO

from flask import Response

from smartshop.presentation.i18n import money


def _spreadsheet_cell(value):
    if isinstance(value, str) and (
        value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@'))
    ):
        return "'" + value
    return value


def _download(filename, header, records):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows([_spreadsheet_cell(value) for value in row] for row in records)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}.csv"'},
    )


def inventory(rows):
    return _download(
        'inventory-report',
        ('Product ID', 'Product', 'Category', 'Available Quantity', 'Last Restocked'),
        ((product.id, product.name, product.category, product.stock, restocked)
         for product, restocked in rows),
    )


def sales(start, end, rows, top, bottom, revenue, units):
    top_ranks = {row.id: rank for rank, row in enumerate(top, 1)}
    bottom_ranks = {row.id: rank for rank, row in enumerate(bottom, 1)}
    records = [('Total', start, end, None, None, None, units, money(revenue), None, None)]
    records.extend(
        ('Product', start, end, row.id, row.name, row.category, row.quantity, money(row.revenue),
         top_ranks.get(row.id), bottom_ranks.get(row.id))
        for row in rows
    )
    return _download(
        'sales-report',
        ('Row Type', 'Start Date (UTC)', 'End Date (UTC)', 'Product ID', 'Product', 'Category',
         'Units Sold', 'Sales (CAD)', 'Most Sold Rank', 'Least Sold Rank'),
        records,
    )


def activity(start, end, days, total, new, busiest, quietest):
    records = [('Total', start, end, None, total, new, total - new, None, None)]
    records.extend(
        ('Day', start, end, day, count, None, None, count == busiest, count == quietest)
        for day, count in days
    )
    return _download(
        'customer-activity-report',
        ('Row Type', 'Start Date (UTC)', 'End Date (UTC)', 'Date (UTC)', 'Customers', 'New Customers',
         'Returning Customers', 'Busiest', 'Quietest'),
        records,
    )


def customer(start, end, purchases, rows, spending):
    records = [('Total', start, end, None, None, None, None, None, None, money(spending))]
    records.extend(
        ('Purchase', start, end, purchase.created_at.isoformat(), purchase.id, None, None, None, None,
         money(purchase.total_cents))
        for purchase in purchases
    )
    records.extend(
        ('Product', start, end, None, None, row.id, row.name, row.category, row.quantity, money(row.revenue))
        for row in rows
    )
    return _download(
        'my-purchase-report',
        ('Row Type', 'Start Date (UTC)', 'End Date (UTC)', 'Purchased At (UTC)', 'Receipt ID',
         'Product ID', 'Product', 'Category', 'Units', 'Amount (CAD)'),
        records,
    )
