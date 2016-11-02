import re
import openpyxl
from datetime import datetime, date
from datatypes import datastore_type

from ckanext.recombinant.errors import BadExcelData

HEADER_ROWS = 3

def read_excel(f, file_contents=None):
    """
    Return a generator that opens the excel file f (name or file object)
    and then produces ((sheet-name, org-name), row1, row2, ...)
    :param: f: file name or xlsx file object

    :return: Generator that opens the excel file f
    and then produces:
        (sheet-name, org-name, column_names, data_rows_generator)
        ...
    :rtype: generator
    """
    wb = openpyxl.load_workbook(f, read_only=True)

    for sheetname in wb.sheetnames:
        if sheetname == 'reference':
            return
        sheet = wb[sheetname]
        rowiter = sheet.rows
        organization_row = next(rowiter)

        label_row = next(rowiter)
        names_row = next(rowiter)

        yield (
            sheetname,
            organization_row[0].value,
            [c.value for c in names_row],
            _filter_bumf(rowiter))


def _filter_bumf(rowiter):
    for row in rowiter:
        values = [c.value for c in row]
        # return next non-empty row
        if not all(_is_bumf(v) for v in values):
            yield values


def _is_bumf(value):
    """
    Return true if this value is filler, en route to skipping over empty lines

    :param value: value to check
    :type value: object

    :return: whether the value is filler
    :rtype: bool
    """
    if type(value) in (unicode, str):
        return value.strip() == ''
    return value is None


def _canonicalize(dirty, dstore_tag):
    """
    Canonicalize dirty input from xlrd to align with
    recombinant.json datastore type specified in dstore_tag.

    :param dirty: dirty cell content as read through xlrd
    :type dirty: object
    :param dstore_tag: datastore_type specifier in (JSON) schema for cell
    :type dstore_tag: str

    :return: Canonicalized cell input
    :rtype: float or unicode

    Raises BadExcelData on formula cells
    """
    dtype = datastore_type[dstore_tag]
    if dirty is None:
        return dtype.default
    elif isinstance(dirty, float) or isinstance(dirty, int):
        if dtype.numeric:
            # XXX truncate decimal values to behave the same as strings
            return unicode(int(dirty // 1))
        else:
            return unicode(dirty) # FIXME ckan2.1 datastore?-- float(dirty)

    elif (isinstance(dirty, basestring)) and (dirty.strip() == ''):
        # Content trims to empty: default
        return dtype.default
    elif not dtype.numeric:
        if dtype.tag == 'money':
            # User has overridden Excel format string, probably adding currency
            # markers or digit group separators (e.g.,fr-CA uses 1$ (not $1)).
            # Truncate any trailing decimal digits, retain int
            # part, and cast as numeric string.
            canon = re.sub(r'[^0-9]', '', re.sub(r'\.[0-9 ]+$', '', unicode(dirty)))
            return unicode(canon)
        elif dtype.tag == 'date' and isinstance(dirty, datetime):
            return u'%04d-%02d-%02d' % (dirty.year, dirty.month, dirty.day)

        if unicode(dirty).startswith('='):
            raise BadExcelData('Formulas are not supported')
        return unicode(dirty)

    # dirty is numeric: truncate trailing decimal digits, retain int part
    canon = re.sub(r'[^0-9]', '', unicode(dirty).split('.')[0])
    if not canon:
        return 0
    return unicode(canon) # FIXME ckan2.1 datastore?-- float(dirty)


def get_records(rows, fields):
    """
    Truncate/pad empty/missing records to expected row length, canonicalize
    cell content, and return resulting record list.

    :param upload_data: generator producing rows of content
    :type upload_data: generator
    :param fields: collection of fields specified in JSON schema
    :type fields: list or tuple

    :return: canonicalized records of specified upload data
    :rtype: tuple of dicts
    """
    records = []
    for n, row in enumerate(rows):
        # trailing cells might be empty: trim row to fit
        while (row and
                (len(row) > len(fields)) and
                (row[-1] is None or row[-1] == '')):
            row.pop()
        while row and (len(row) < len(fields)):
            row.append(None) # placeholder: canonicalize once only, below

        try:
            records.append(
                dict((
                    f['datastore_id'],
                    _canonicalize(v, f['datastore_type']))
                for f, v in zip(fields, row)))
        except BadExcelData, e:
            raise BadExcelData('Row %d: ' % (n + HEADER_ROWS + 1) + e.message)

    return records
