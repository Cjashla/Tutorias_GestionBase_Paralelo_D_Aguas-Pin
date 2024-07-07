import mysql.connector
import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import chardet

def mostrar_menu():
    print("\nMenu de Opciones:")
    print("1. Generacion de Disparadores de Auditoria")
    print("2. Logs")
    print("3. Salir")

def obtener_columnas_tabla(cursor, tabla):
    cursor.execute(f"SHOW COLUMNS FROM {tabla}")
    columnas = cursor.fetchall()
    nombres_columnas = [columna[0] for columna in columnas]
    return nombres_columnas

def crear_funcion_trigger(cursor, tabla):
    columnas = obtener_columnas_tabla(cursor, tabla)

    insert_values = ", ".join([f"'new_{columna.lower()}', NEW.{columna}" for columna in columnas])
    update_values = ", ".join([f"'old_{columna.lower()}', OLD.{columna}, 'new_{columna.lower()}', NEW.{columna}" for columna in columnas])
    delete_values = ", ".join([f"'old_{columna.lower()}', OLD.{columna}" for columna in columnas])

    funcion_sql = f"""
    CREATE OR REPLACE TRIGGER audit_{tabla}_after_insert
    AFTER INSERT ON {tabla}
    FOR EACH ROW
    BEGIN
        INSERT INTO auditoria (nombre_tabla, usuario_db, accion, descripcion_cambios)
        VALUES ('{tabla}', USER(), 'INSERT', JSON_OBJECT({insert_values}));
    END;
    """

    trigger_sql = f"""
    CREATE OR REPLACE TRIGGER audit_{tabla}_after_update
    AFTER UPDATE ON {tabla}
    FOR EACH ROW
    BEGIN
        INSERT INTO auditoria (nombre_tabla, usuario_db, accion, descripcion_cambios)
        VALUES ('{tabla}', USER(), 'UPDATE', JSON_OBJECT({update_values}));
    END;

    CREATE OR REPLACE TRIGGER audit_{tabla}_after_delete
    AFTER DELETE ON {tabla}
    FOR EACH ROW
    BEGIN
        INSERT INTO auditoria (nombre_tabla, usuario_db, accion, descripcion_cambios)
        VALUES ('{tabla}', USER(), 'DELETE', JSON_OBJECT({delete_values}));
    END;
    """

    return funcion_sql, trigger_sql

def opcion1(cursor):
    print("Ejecutando Opción 1...")
    
    cursor.execute("SHOW TABLES")
    tablas = cursor.fetchall()
    
    print("\nTablas disponibles en la base de datos:")
    for idx, tabla in enumerate(tablas):
        print(f"{idx + 1}. {tabla[0]}")
    
    seleccion = input("\nSeleccione las tablas para auditar (separadas por coma, o 'all' para todas): ")
    
    if seleccion.lower() == 'all':
        tablas_seleccionadas = [tabla[0] for tabla in tablas]
    else:
        try:
            indices = map(int, seleccion.split(','))
            tablas_seleccionadas = [tablas[idx - 1][0] for idx in indices]
        except ValueError:
            print("Selección inválida. Por favor, use números separados por comas.")
            return

    with open("auditoria_triggers.sql", "w", encoding="utf-8") as sql_file:
        for tabla in tablas_seleccionadas:
            if tabla.lower() != 'auditoria':
                columnas = obtener_columnas_tabla(cursor, tabla)
                funcion_sql, trigger_sql = crear_funcion_trigger(cursor, tabla)
                sql_file.write(funcion_sql)
                sql_file.write(trigger_sql)
                
                try:
                    cursor.execute(funcion_sql)
                except mysql.connector.Error as err:
                    print(f"Error al ejecutar el disparador para {tabla}: {err}")

                try:
                    cursor.execute(trigger_sql, multi=True)
                except mysql.connector.Error as err:
                    print(f"Error al ejecutar el disparador para {tabla}: {err}")

    print("\nDisparadores de auditoría creados exitosamente y guardados en 'auditoria_triggers.sql'.")

def generar_pdf(logs, pdf_filename):
    doc = SimpleDocTemplate(pdf_filename, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    custom_style = ParagraphStyle(
        name='CustomStyle',
        fontSize=9,
        leading=10,
        spaceAfter=4,
        wordWrap='CJK'
    )
    date_time_style = ParagraphStyle(
        name='DateTimeStyle',
        fontSize=9,
        leading=10,
        spaceAfter=4,
        wordWrap='CJK',
        alignment=1
    )
    elements = []

    title = "Reporte de Logs"
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Spacer(1, 12))

    col_widths = [100, 60, 60, 80, 80, 60, 240]
    data = [["Fecha y Hora", "ID del Proceso", "Usuario", "Base de Datos", "Aplicación", "Nivel del Log", "Mensaje"]]
    
    for log in logs:
        fecha_hora = log['fecha_hora'].split(" ")
        fecha = fecha_hora[0]
        hora = fecha_hora[1]
        fecha_hora_formateada = Paragraph(f"{fecha}<br/>{hora}", date_time_style)
        row = [
            fecha_hora_formateada,
            log['id_proceso'],
            log['usuario'],
            log['base_datos'],
            log['aplicacion'],
            log['nivel'],
            Paragraph(log['mensaje'], custom_style)
        ]
        data.append(row)

    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    print(f"Reporte PDF generado: {pdf_filename}")

def obtener_usuarios(cursor):
    cursor.execute("SELECT user FROM mysql.user WHERE host='localhost'")
    return [usuario[0] for usuario in cursor.fetchall()]

def leer_logs_en_rango(log_directory, fecha_inicio, fecha_fin, usuario):
    logs_combinados = []
    try:
        fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d %H:%M:%S")
        fecha_fin = datetime.strptime(fecha_fin, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print("Formato de fecha y hora incorrecto.")
        return []

    log_files = sorted(os.listdir(log_directory))
    for log_file in log_files:
        log_path = os.path.join(log_directory, log_file)
        if os.path.isfile(log_path) and log_path.endswith(".log"):  # Filtrar solo archivos de log
            with open(log_path, 'r', encoding='utf-8') as file:
                for line in file:
                    match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) -(\d{2}) \[(\d+)\]: \[(\d+-\d+)\] user=(\w+),db=(\w+),app=\[(.*?)\] (\w+): (.+)", line)
                    if match:
                        log_fecha = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                        if fecha_inicio <= log_fecha <= fecha_fin and match.group(5) == usuario:
                            log_entry = {
                                'fecha_hora': match.group(1),
                                'id_proceso': match.group(3),
                                'usuario': match.group(5),
                                'base_datos': match.group(6),
                                'aplicacion': match.group(7),
                                'nivel': match.group(8),
                                'mensaje': match.group(9)
                            }
                            logs_combinados.append(log_entry)
    return logs_combinados

def opcion2(cursor):
    print("Ejecutando Opción 2...")

    usuarios = obtener_usuarios(cursor)
    print("\nUsuarios disponibles:")
    for idx, usuario in enumerate(usuarios):
        print(f"{idx + 1}. {usuario}")

    seleccion_usuario = input("\nSeleccione un usuario (número): ")
    try:
        usuario = usuarios[int(seleccion_usuario) - 1]
    except (IndexError, ValueError):
        print("Selección de usuario inválida.")
        return

    while True:
        fecha_inicio = input("Ingrese la fecha y hora de inicio (YYYY-MM-DD HH:MM:SS): ")
        fecha_fin = input("Ingrese la fecha y hora de fin (YYYY-MM-DD HH:MM:SS): ")
        if validar_fechas(fecha_inicio, fecha_fin):
            break

    log_directory = r"C:\Program Files\MariaDB 11.3\data"  # Ajustar la ruta al directorio de logs de MariaDB
    logs = leer_logs_en_rango(log_directory, fecha_inicio, fecha_fin, usuario)
    
    if not logs:
        print("No se encontraron registros para los criterios especificados.")
    else:
        print("\nContenido de los logs seleccionados:\n")
        for log in logs:
            print(f"{log['fecha_hora']} - {log['id_proceso']} - {log['usuario']} - {log['base_datos']} - {log['aplicacion']} - {log['nivel']} - {log['mensaje']}")

        pdf_filename = input("Ingrese el nombre del archivo PDF a generar: ") + ".pdf"
        generar_pdf(logs, pdf_filename)

def validar_fechas(fecha_inicio, fecha_fin):
    try:
        datetime.strptime(fecha_inicio, "%Y-%m-%d %H:%M:%S")
        datetime.strptime(fecha_fin, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        print("Formato de fecha y hora incorrecto. Por favor, intente nuevamente.")
        return False

def main():
    database = "tienda"
    try:
        conexion = mysql.connector.connect(
            host="localhost",
            port="3308",
            database=database,
            user="root",
            password="123"
        )
        conexion.autocommit = True
        cursor = conexion.cursor()
        
        while True:
            mostrar_menu()
            opcion = input("Selecciona una opción: ")
            if opcion == '1':
                opcion1(cursor)
            elif opcion == '2':
                opcion2(cursor)
            elif opcion == '3':
                print("Saliendo del programa...")
                break
            else:
                print("Opción no válida. Por favor, intenta de nuevo.")
    except mysql.connector.Error as e:
        print(f"Error en la conexión a la base de datos: {e}")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conexion' in locals() and conexion.is_connected():
            conexion.close()

if __name__ == '__main__':
    main()
