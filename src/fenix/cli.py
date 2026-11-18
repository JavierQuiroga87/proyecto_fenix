
"""Interfaz de línea de comandos del sistema Fénix."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def command_init_queues(args):
    from fenix.services.sqs import ensure_queues

    prefix = os.getenv("QUEUE_PREFIX", "fenix-grupo01")

    try:
        ensure_queues(prefix)
        print("Colas inicializadas correctamente.")
    except NotImplementedError as error:
        print(f"Función pendiente de I2: {error}", file=sys.stderr)
        return 1

    return 0


def command_setup_demo(args):
    from fenix.services import demo

    function = getattr(demo, "setup_demo", None)

    if not callable(function):
        print("setup-demo está pendiente de implementación por I2.")
        return 1

    function()
    print("Entorno de demostración preparado.")
    return 0


def command_fault(args):
    from fenix.services import demo

    function = getattr(demo, "fault", None)

    if not callable(function):
        print("fault está pendiente de implementación por I2.")
        return 1

    function(args.resource_id)
    print(f"Falla solicitada para {args.resource_id}.")
    return 0


def command_worker(args):
    from fenix.services.worker import run

    run(once=args.once)
    return 0


def command_send(args):
    from fenix.services.events import validate
    from fenix.services.sqs import queue_url, publish
    from fenix.services.worker import load_inventory

    event_path = Path(args.event_file)

    if not event_path.is_file():
        print(f"No se encontró el archivo: {event_path}", file=sys.stderr)
        return 1

    try:
        with event_path.open("r", encoding="utf-8") as file:
            event = json.load(file)

        inventory = load_inventory()
        event = validate(event, inventory)

        prefix = os.getenv("QUEUE_PREFIX", "fenix-grupo01")
        url = queue_url(prefix)

        publish(url, event)

        print("Evento publicado correctamente en SQS.")
        return 0

    except Exception as error:
        print(f"No se pudo enviar el evento: {error}", file=sys.stderr)
        return 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="Operador de infraestructura del sistema Fénix."
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init_parser = subparsers.add_parser(
        "init-queues",
        help="Inicializa las colas.",
    )
    init_parser.set_defaults(func=command_init_queues)

    demo_parser = subparsers.add_parser(
        "setup-demo",
        help="Prepara el entorno de demostración.",
    )
    demo_parser.set_defaults(func=command_setup_demo)

    fault_parser = subparsers.add_parser(
        "fault",
        help="Simula una falla en un recurso.",
    )
    fault_parser.add_argument("resource_id")
    fault_parser.set_defaults(func=command_fault)

    worker_parser = subparsers.add_parser(
        "worker",
        help="Inicia el trabajador de eventos.",
    )
    worker_parser.add_argument(
        "--once",
        action="store_true",
        help="Consulta una vez y finaliza.",
    )
    worker_parser.set_defaults(func=command_worker)

    send_parser = subparsers.add_parser(
        "send",
        help="Envía un evento desde un archivo JSON.",
    )
    send_parser.add_argument("event_file")
    send_parser.set_defaults(func=command_send)

    return parser


def main():
    logging.basicConfig(level=logging.INFO)

    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.func(args)
    except Exception:
        logging.exception("Error durante la ejecución del comando.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
