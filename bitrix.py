import os
import uuid

import requests

from dotenv import load_dotenv

load_dotenv()
WEB_HOOK = os.getenv('WEB_HOOK')
API_HOST = os.getenv('API_HOST')

IBLOCK_TYPE_ID = 'lists_socnet'
IBLOCK_CODE = 'work_time_{}'  # код информационного блока
SOCNET_GROUP_ID = 22
LIST_TEMPLATE = 'mcko.bitrix24.ru/workgroups/group/{}/lists/{}/view/0/'.format(SOCNET_GROUP_ID, '{}')


def create_element(event, fields):
    """Создает элемент в списке event в Битрикс."""

    command = 'lists.element.add'
    url = WEB_HOOK + command
    params = {
        'IBLOCK_TYPE_ID': IBLOCK_TYPE_ID,
        'SOCNET_GROUP_ID': SOCNET_GROUP_ID,
        'IBLOCK_CODE': IBLOCK_CODE.format(event),
        'ELEMENT_CODE': uuid.uuid1().int,
        'FIELDS': fields
    }
    return requests.post(url, json=params)
