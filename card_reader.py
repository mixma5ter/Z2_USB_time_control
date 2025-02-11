import sys
from datetime import datetime

import requests
import serial

# Настройки COM-порта
from bitrix import create_element, API_HOST

port = 'COM5'
baudrate = 9600
bytesize = serial.EIGHTBITS
parity = serial.PARITY_NONE
stopbits = serial.STOPBITS_ONE


def get_user_name(card_number):
    try:
        res = requests.get(f'{API_HOST}employees/{card_number}/')
        res.raise_for_status()
        data = res.json()
        return data['employee_name']
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None


def get_user_name_and_patch_user_data(card_number):
    try:
        res = requests.get(f'{API_HOST}employees/{card_number}/')
        res.raise_for_status()
        data = res.json()
        current_status = data['is_active']
        new_status = not current_status

        current_time = datetime.now().isoformat()

        patch_data = {'is_active': new_status, 'last_checkin': current_time}
        patch_res = requests.patch(f'{API_HOST}employees/{card_number}/', json=patch_data)
        patch_res.raise_for_status()

        # Преобразуем last_checkin в datetime объект
        last_checkin_dt = datetime.fromisoformat(data['last_checkin'].replace('Z', '+00:00')).replace(tzinfo=None)

        return data['employee_name'], last_checkin_dt, current_time, new_status

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None, None, None, None


try:
    ser = serial.Serial(port, baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits)
    if ser.is_open:
        print(f"Connected to {port}")
    else:
        print("Card reader not connected")
        ser.close()
        sys.exit()

    while True:
        line = ser.readline().decode('ascii', errors='ignore').strip()
        if "Em-Marine" in line:
            card_data = line.split()
            card_number = card_data[1].split(',')[1]  # Извлекаем номер карты

            try:
                user_name, last_checkin_time, current_time_iso, user_status = get_user_name_and_patch_user_data(
                    card_number)
                if user_name:
                    print(f"Имя сотрудника: {user_name}")
                    print(f"Активность: {'Вход' if user_status else 'Выход'}")
                else:
                    print("Сотрудник не найден.")

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
                        print(f"Ошибка при вычислении time_diff: {e}")
                        time_diff_formatted = "-"

                fields = {
                    'NAME': card_number,
                    'PROPERTY_3246': user_name,
                    'PROPERTY_3248': current_time_iso,
                    'PROPERTY_3348': 'Вход' if user_status else 'Выход',
                    'PROPERTY_3352': time_diff_formatted,
                }

                response = create_element(2025, fields)
                print(f"Данные отправлены в Битрикс24: {response}")

            except KeyError:
                print(f"Номер карты {card_number} не найден в базе данных.")
            except requests.exceptions.RequestException as e:
                print(f"Ошибка отправки данных в Битрикс24: {e}")
        elif "No card" in line:
            print("...")
        else:
            print("Эта карта не поддерживается")

except serial.SerialException as e:
    print(f"Error: {e}")

finally:
    if 'ser' in locals() and ser.is_open:
        ser.close()
