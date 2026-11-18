import boto3
from moto import mock_aws
from unittest.mock import patch
from fenix.services import sqs


def test_sqs_with_moto():
    with mock_aws():
        moto_client = boto3.client(
            "sqs",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )

        url = moto_client.create_queue(
            QueueName="fenix-grupo01-events"
        )["QueueUrl"]

        with patch("fenix.services.sqs.client", return_value=moto_client):
            message_id = sqs.publish(
                url,
                {
                    "event_id": "evento-001",
                    "event_type": "instance.stopped",
                },
            )

            messages = sqs.receive(url)

            assert messages, "No se recibio ningun mensaje."
            assert messages[0]["Body"], "El mensaje llego vacio."
            assert message_id, "No se genero un ID para el mensaje."

            sqs.acknowledge(url, messages[0]["ReceiptHandle"])

        print("Prueba de publicacion, recepcion y ACK con Moto exitosa.")


if __name__ == "__main__":
    test_sqs_with_moto()