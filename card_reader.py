import logging
import sys
from datetime import datetime

import requests
import serial

from bitrix import create_element, API_HOST

# Настройки логирования
logging.basicConfig(
    level=logging.DEBUG,  # Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("log.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

TIMEOUT = 3  # Таймаут запроса к БД

# Настройки COM-порта
port = 'COM3'
baudrate = 9600
bytesize = serial.EIGHTBITS
parity = serial.PARITY_NONE
stopbits = serial.STOPBITS_ONE


def get_and_patch_user_data(card_number):
    logging.debug(f"Processing card number: {card_number}")

    try:
        res = requests.get(f'{API_HOST}employees/{card_number}/')
        res.raise_for_status()
        data = res.json()
        current_user_status = data['is_active']
        comment = None
        now = datetime.now()

        if data.get('last_checkin'):
            # Преобразуем last_checkin в datetime объект
            last_checkin_dt = datetime.fromisoformat(data['last_checkin'].replace('Z', '+00:00')).replace(tzinfo=None)
        else:
            last_checkin_dt = now

        if now.date() != last_checkin_dt.date() and current_user_status:
            comment = "Некорректное завершение рабочего дня"
            new_user_status = True
        else:
            new_user_status = not current_user_status

        current_time = datetime.now().isoformat()

        patch_data = {'is_active': new_user_status, 'last_checkin': current_time}
        patch_res = requests.patch(f'{API_HOST}employees/{card_number}/', json=patch_data, timeout=TIMEOUT)
        logging.debug(f"Request to send API: {card_number}")
        patch_res.raise_for_status()

        return data['employee_name'], last_checkin_dt, current_time, new_user_status, comment

    except requests.exceptions.RequestException as e:
        logging.error(f"Error: {e}")
        return None, None, None, None, None


if __name__ == '__main__':
    try:
        ser = serial.Serial(port, baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits)
        if ser.is_open:
            logging.info(f"Connected to {port}")
        else:
            logging.warning("Card reader not connected")
            ser.close()
            sys.exit()

        while True:
            logging.info("\n")
            logging.info("Waiting for data...")
            line = ser.readline().decode('ascii', errors='ignore').strip()
            logging.debug(f"Received line: {line}")

            if "Em-Marine" in line:
                card_data = line.split()
                card_number = card_data[1].split(',')[1]  # Извлекаем номер карты
                logging.info(f"Card number read: {card_number}")

                try:
                    user_name, last_checkin_time, current_time_iso, user_status, comment = get_and_patch_user_data(card_number)
                    if user_name:
                        logging.info(f"User: {user_name}")
                        logging.info(f"Activity: {'Вход' if user_status else 'Выход'}")
                        if comment:
                            logging.info(f"Comment: {comment}")
                    else:
                        logging.warning(f"User with card number {card_number} not found")

                    # Получаем текущую дату и время
                    now = datetime.now()
                    time_diff_formatted = "-"

                    if not user_status:  # Если user_status == False (т.е. "Выход")
                        try:
                            time_diff = now - last_checkin_time
                            time_diff_seconds = time_diff.total_seconds()
                            hours = int(time_diff_seconds // 3600)
                            minutes = int((time_diff_seconds % 3600) // 60)
                            seconds = int(time_diff_seconds % 60)
                            time_diff_formatted = f"{hours:02}:{minutes:02}:{seconds:02}"

                        except (TypeError, ValueError) as e:
                            logging.error(f"Error: {e}")
                            time_diff_formatted = "-"

                    if comment:
                        time_diff_formatted = comment

                    fields = {
                        'NAME': card_number,
                        'PROPERTY_3246': user_name,
                        'PROPERTY_3248': current_time_iso,
                        'PROPERTY_3348': 'Вход' if user_status else 'Выход',
                        'PROPERTY_3352': time_diff_formatted,
                    }

                    response = create_element(2025, fields)
                    logging.debug(f"Data sent to Bitrix24: {response}")

                except KeyError:
                    logging.error(f"Card number {card_number} does not exist")
                except requests.exceptions.RequestException as e:
                    logging.exception(f"Error: {e}")

            elif "No card" in line:
                print("...")
            else:
                logging.warning("The card is not supported")

    except serial.SerialException as e:
        logging.error(f"Serial port error: {e}")
    except Exception as e:
        logging.exception(f"Error: {e}")

    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
