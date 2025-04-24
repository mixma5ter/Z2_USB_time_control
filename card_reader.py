import logging
import re
import sys
import time
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


def read_card_data_non_blocking(ser):
    """Читает данные с последовательного порта неблокирующим способом
       и проверяет на начало и конец сообщения."""
    data = ser.in_waiting
    if data > 0:
        line = ser.read(data).decode('ascii', errors='ignore').strip()

        # Проверка на "Em-Marine" и номер карты в конце
        if "Em-Marine" in line and re.search(r"\d+$", line):
            return line
        else:
            # Добавляем таймаут для обработки фрагментированных сообщений
            start_time = time.time()
            buffer = line
            while time.time() - start_time < 0.1:  # Таймаут 0.1 секунды
                more_data = ser.in_waiting
                if more_data > 0:
                    buffer += ser.read(more_data).decode('ascii', errors='ignore').strip()
                    if "Em-Marine" in buffer and re.search(r"\d+$", buffer):
                        return buffer
                time.sleep(0.01)  # Небольшая задержка, чтобы не перегружать процессор
            logging.warning(f"Incomplete or invalid card data: {buffer}")  # Логируем неполные данные

    return None


def read_card_data_until_complete(ser):
    buffer = ""
    while True:
        received_data = ser.readline().decode('utf-8', errors='ignore').strip()
        if received_data:
            buffer += received_data
            if "Em-Marine" in buffer and re.search(r"\d+$", buffer):  # Проверка на номер карты в конце
                break  # Сообщение полное
        # Здесь можно добавить таймаут, аналогично предыдущему примеру,
        # чтобы избежать бесконечного цикла, если конец сообщения не приходит

    return buffer


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
    show_waiting_message = True
    ser = None
    while True:
        try:
            if ser is None or not ser.is_open:
                ser = serial.Serial(port, baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits)
                if ser.is_open:
                    logging.info(f"Connected to {port}")
                    show_waiting_message = True
                else:
                    logging.warning("Failed to connect to card reader. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue

            if show_waiting_message:
                logging.info("\nWaiting for data...")
                show_waiting_message = False

            line = read_card_data_non_blocking(ser)

            if line:
                logging.debug(f"Received line: {line}")
                if "Em-Marine" in line:
                    try:
                        card_number = line.split()[1].split(',')[1]
                        logging.info(f"Card number read: {card_number}")

                        user_name, last_checkin_time, current_time_iso, user_status, comment = get_and_patch_user_data(
                            card_number)

                        if user_name is None:
                            logging.warning(f"User with card number {card_number} not found")
                            continue

                        logging.info(f"User: {user_name}")
                        activity = 'Вход' if user_status else 'Выход'
                        logging.info(f"Activity: {activity}")
                        if comment:
                            logging.info(f"Comment: {comment}")

                        time_diff_formatted = "-"

                        if not user_status:  # Если user_status == False (т.е. "Выход")
                            try:
                                time_diff = datetime.now() - last_checkin_time
                                time_diff_seconds = time_diff.total_seconds()
                                hours = int(time_diff_seconds // 3600)
                                minutes = int((time_diff_seconds % 3600) // 60)
                                seconds = int(time_diff_seconds % 60)
                                time_diff_formatted = f"{hours:02}:{minutes:02}:{seconds:02}"
                                logging.debug(f"Time difference: {time_diff_formatted}")

                            except (TypeError, ValueError) as e:
                                logging.error(f"Error: {e}")
                                time_diff_formatted = "-"

                        fields = {
                            'NAME': card_number,  # Название
                            'PROPERTY_3246': user_name,  # ФИО
                            'PROPERTY_3248': current_time_iso,  # Время регистрации ключа
                            'PROPERTY_3348': activity,  # Активность
                            'PROPERTY_3352': time_diff_formatted,  # Длительность
                            'PROPERTY_3510': comment,  # Комментарий
                        }

                        response = create_element(2025, fields, timeout=TIMEOUT)
                        if response is None:
                            logging.error("Error communicating with Bitrix24")
                        else:
                            logging.debug(f"Data sent to Bitrix24: {response}")

                    except (IndexError, KeyError, ValueError) as e:  # Объединяем обработку исключений
                        logging.error(f"Error processing card data: {e}")
                    except requests.exceptions.RequestException as e:
                        logging.exception(f"Error communicating with Bitrix24: {e}")

                elif "No card" in line:
                    print("\n...")
                else:
                    logging.warning("The card is not supported")
            else:
                show_waiting_message = False
                time.sleep(0.1)  # Пауза, чтобы не перегружать процессор

        except serial.SerialException as e:
            logging.error(f"Serial port error: {e}")
            if ser:
                ser.close()
            ser = None
            time.sleep(5)
        except KeyboardInterrupt:
            logging.info("Exiting...")
            if ser:
                ser.close()
            sys.exit()
        except Exception as e:
            logging.exception(f"An unexpected error occurred: {e}")
            if ser:
                ser.close()
            ser = None
            time.sleep(5)
