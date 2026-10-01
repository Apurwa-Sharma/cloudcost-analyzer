"""Read-only AWS resource discovery using Boto3 and the AWS CLI credential chain."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    TokenRetrievalError,
)

CLOUDWATCH_NAMESPACES = (
    "AWS/EC2",
    "AWS/EBS",
    "AWS/RDS",
    "AWS/S3",
)
CLOUDWATCH_METRICS_PER_NAMESPACE = 200


class AwsScannerError(Exception):
    """Base error for AWS scanning failures."""

    def __init__(self, message: str, code: str = "AWS_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class CredentialsNotConfiguredError(AwsScannerError):
    def __init__(self, message: str = "AWS CLI credentials are not configured."):
        super().__init__(message, code="CREDENTIALS_NOT_CONFIGURED", status_code=401)


class InvalidCredentialsError(AwsScannerError):
    def __init__(self, message: str = "AWS credentials are invalid."):
        super().__init__(message, code="INVALID_CREDENTIALS", status_code=401)


class AccessDeniedError(AwsScannerError):
    def __init__(self, message: str = "Access denied for the requested AWS operation."):
        super().__init__(message, code="ACCESS_DENIED", status_code=403)


class InvalidRegionError(AwsScannerError):
    def __init__(self, region: str):
        super().__init__(
            f"Invalid AWS region: {region}",
            code="INVALID_REGION",
            status_code=400,
        )


class AwsApiError(AwsScannerError):
    def __init__(self, message: str):
        super().__init__(message, code="AWS_API_ERROR", status_code=502)


class AwsConnectionError(AwsScannerError):
    def __init__(self, message: str = "Unable to connect to AWS APIs."):
        super().__init__(message, code="AWS_CONNECTION_ERROR", status_code=503)


def _env_region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


def _env_profile() -> str | None:
    profile = os.getenv("AWS_PROFILE", "").strip()
    return profile or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tags_to_dict(tags: list[dict[str, str]] | None) -> dict[str, str]:
    if not tags:
        return {}
    return {tag.get("Key", ""): tag.get("Value", "") for tag in tags if tag.get("Key")}


def _name_from_tags(tags: dict[str, str], fallback: str) -> str:
    return tags.get("Name") or fallback


def _resource(
    *,
    service: str,
    resource_type: str,
    resource_id: str,
    resource_name: str,
    region: str,
    status: str,
    configuration: dict[str, Any],
    tags: dict[str, str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "service": service,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "region": region,
        "status": status,
        "configuration": configuration,
        "tags": tags,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _client_error_message(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    code = error.get("Code", "Unknown")
    message = error.get("Message", str(exc))
    return f"{code}: {message}"


def _raise_from_client_error(exc: ClientError) -> None:
    code = _client_error_code(exc)
    message = _client_error_message(exc)

    if code in {
        "InvalidClientTokenId",
        "UnrecognizedClientException",
        "SignatureDoesNotMatch",
        "AuthFailure",
        "InvalidUserID.NotFound",
        "ExpiredToken",
        "ExpiredTokenException",
        "RequestExpired",
    }:
        raise InvalidCredentialsError(message) from exc

    if code in {
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "AuthorizationError",
        "AuthFailure.UnauthorizedOperation",
    }:
        raise AccessDeniedError(message) from exc

    if code in {"InvalidRegion", "OptInRequired", "UnknownEndpoint"}:
        raise AwsApiError(message) from exc

    raise AwsApiError(message) from exc


def _raise_from_boto_error(exc: Exception) -> None:
    if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
        raise CredentialsNotConfiguredError(
            "AWS CLI/credentials are not configured. Run `aws configure`."
        ) from exc
    if isinstance(exc, TokenRetrievalError):
        raise InvalidCredentialsError("Unable to retrieve AWS credentials or session token.") from exc
    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError)):
        raise AwsConnectionError(str(exc)) from exc
    if isinstance(exc, ClientError):
        _raise_from_client_error(exc)
    if isinstance(exc, BotoCoreError):
        raise AwsApiError(str(exc)) from exc
    raise AwsApiError(str(exc)) from exc


def create_session(profile_name: str | None = None) -> boto3.Session:
    profile = profile_name if profile_name is not None else _env_profile()
    try:
        return boto3.Session(profile_name=profile)
    except Exception as exc:  # ProfileNotFound and similar
        name = type(exc).__name__
        if "ProfileNotFound" in name or "profile" in str(exc).lower():
            raise CredentialsNotConfiguredError(
                f"AWS profile '{profile}' was not found. Configure it with `aws configure`."
            ) from exc
        _raise_from_boto_error(exc)


def _sts_identity(session: boto3.Session) -> dict[str, str]:
    try:
        sts = session.client("sts", region_name=_env_region())
        identity = sts.get_caller_identity()
        return {
            "account_id": identity.get("Account", ""),
            "arn": identity.get("Arn", ""),
            "user_id": identity.get("UserId", ""),
        }
    except Exception as exc:
        _raise_from_boto_error(exc)


def list_aws_regions(session: boto3.Session | None = None) -> list[dict[str, str]]:
    session = session or create_session()
    try:
        ec2 = session.client("ec2", region_name=_env_region())
        response = ec2.describe_regions(AllRegions=False)
        regions = [
            {
                "region": item["RegionName"],
                "endpoint": item.get("Endpoint", ""),
                "opt_in_status": item.get("OptInStatus", ""),
            }
            for item in response.get("Regions", [])
        ]
        return sorted(regions, key=lambda item: item["region"])
    except Exception as exc:
        _raise_from_boto_error(exc)


def _assert_valid_region(session: boto3.Session, region: str) -> None:
    region = (region or "").strip()
    if not region:
        raise InvalidRegionError(region or "(empty)")

    try:
        available = {item["region"] for item in list_aws_regions(session)}
    except AwsScannerError:
        raise
    except Exception as exc:
        _raise_from_boto_error(exc)

    if region not in available:
        raise InvalidRegionError(region)


def _safe_collect(errors: list[dict[str, str]], service: str, collector) -> list[dict[str, Any]]:
    try:
        return collector()
    except AwsScannerError as exc:
        if exc.code in {"CREDENTIALS_NOT_CONFIGURED", "INVALID_CREDENTIALS", "INVALID_REGION"}:
            raise
        errors.append({"service": service, "code": exc.code, "message": exc.message})
        return []
    except Exception as exc:
        try:
            _raise_from_boto_error(exc)
        except AwsScannerError as mapped:
            if mapped.code in {"CREDENTIALS_NOT_CONFIGURED", "INVALID_CREDENTIALS", "INVALID_REGION"}:
                raise
            errors.append({"service": service, "code": mapped.code, "message": mapped.message})
            return []
    return []


def _scan_ec2_instances(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    ec2 = session.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_instances")
    resources: list[dict[str, Any]] = []

    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                tags = _tags_to_dict(instance.get("Tags"))
                instance_id = instance.get("InstanceId", "")
                resources.append(
                    _resource(
                        service="ec2",
                        resource_type="instance",
                        resource_id=instance_id,
                        resource_name=_name_from_tags(tags, instance_id),
                        region=region,
                        status=instance.get("State", {}).get("Name", "unknown"),
                        configuration={
                            "instance_type": instance.get("InstanceType"),
                            "image_id": instance.get("ImageId"),
                            "platform": instance.get("PlatformDetails") or instance.get("Platform"),
                            "architecture": instance.get("Architecture"),
                            "vpc_id": instance.get("VpcId"),
                            "subnet_id": instance.get("SubnetId"),
                            "availability_zone": instance.get("Placement", {}).get("AvailabilityZone"),
                            "private_ip": instance.get("PrivateIpAddress"),
                            "public_ip": instance.get("PublicIpAddress"),
                            "key_name": instance.get("KeyName"),
                            "monitoring": instance.get("Monitoring", {}).get("State"),
                            "security_groups": [
                                {
                                    "group_id": group.get("GroupId"),
                                    "group_name": group.get("GroupName"),
                                }
                                for group in instance.get("SecurityGroups", [])
                            ],
                            "ebs_optimized": instance.get("EbsOptimized"),
                            "root_device_type": instance.get("RootDeviceType"),
                        },
                        tags=tags,
                        metadata={
                            "launch_time": instance.get("LaunchTime").isoformat()
                            if instance.get("LaunchTime")
                            else None,
                            "reservation_id": reservation.get("ReservationId"),
                        },
                    )
                )
    return resources


def _scan_ebs_volumes(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    ec2 = session.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_volumes")
    resources: list[dict[str, Any]] = []

    for page in paginator.paginate():
        for volume in page.get("Volumes", []):
            tags = _tags_to_dict(volume.get("Tags"))
            volume_id = volume.get("VolumeId", "")
            attachments = volume.get("Attachments", [])
            resources.append(
                _resource(
                    service="ec2",
                    resource_type="ebs_volume",
                    resource_id=volume_id,
                    resource_name=_name_from_tags(tags, volume_id),
                    region=region,
                    status=volume.get("State", "unknown"),
                    configuration={
                        "size_gb": volume.get("Size"),
                        "volume_type": volume.get("VolumeType"),
                        "iops": volume.get("Iops"),
                        "throughput": volume.get("Throughput"),
                        "encrypted": volume.get("Encrypted"),
                        "kms_key_id": volume.get("KmsKeyId"),
                        "availability_zone": volume.get("AvailabilityZone"),
                        "snapshot_id": volume.get("SnapshotId"),
                        "multi_attach_enabled": volume.get("MultiAttachEnabled"),
                    },
                    tags=tags,
                    metadata={
                        "create_time": volume.get("CreateTime").isoformat()
                        if volume.get("CreateTime")
                        else None,
                        "attachment_status": attachments[0].get("State") if attachments else "unattached",
                        "attachments": [
                            {
                                "instance_id": item.get("InstanceId"),
                                "device": item.get("Device"),
                                "state": item.get("State"),
                                "delete_on_termination": item.get("DeleteOnTermination"),
                            }
                            for item in attachments
                        ],
                    },
                )
            )
    return resources


def _scan_elastic_ips(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    ec2 = session.client("ec2", region_name=region)
    response = ec2.describe_addresses()
    resources: list[dict[str, Any]] = []

    for address in response.get("Addresses", []):
        tags = _tags_to_dict(address.get("Tags"))
        allocation_id = address.get("AllocationId") or address.get("PublicIp", "")
        associated = bool(address.get("AssociationId") or address.get("InstanceId"))
        resources.append(
            _resource(
                service="ec2",
                resource_type="elastic_ip",
                resource_id=allocation_id,
                resource_name=_name_from_tags(tags, address.get("PublicIp", allocation_id)),
                region=region,
                status="associated" if associated else "unassociated",
                configuration={
                    "public_ip": address.get("PublicIp"),
                    "domain": address.get("Domain"),
                    "allocation_id": address.get("AllocationId"),
                    "association_id": address.get("AssociationId"),
                    "network_interface_id": address.get("NetworkInterfaceId"),
                    "private_ip_address": address.get("PrivateIpAddress"),
                    "public_ipv4_pool": address.get("PublicIpv4Pool"),
                    "network_border_group": address.get("NetworkBorderGroup"),
                },
                tags=tags,
                metadata={"instance_id": address.get("InstanceId")},
            )
        )
    return resources


def _s3_bucket_region(s3, bucket_name: str) -> str:
    location = s3.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
    if location in (None, ""):
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def _s3_lifecycle(s3, bucket_name: str) -> dict[str, Any] | None:
    try:
        response = s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        rules = response.get("Rules", [])
        return {"rule_count": len(rules), "rules": rules}
    except ClientError as exc:
        code = _client_error_code(exc)
        if code in {"NoSuchLifecycleConfiguration", "NoSuchBucket"}:
            return None
        _raise_from_client_error(exc)
    return None


def _scan_s3_buckets(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    s3 = session.client("s3", region_name=region)
    response = s3.list_buckets()
    resources: list[dict[str, Any]] = []

    for bucket in response.get("Buckets", []):
        name = bucket.get("Name", "")
        try:
            bucket_region = _s3_bucket_region(s3, name)
        except ClientError as exc:
            if _client_error_code(exc) in {"AccessDenied", "AccessDeniedException"}:
                continue
            _raise_from_client_error(exc)
            continue

        if bucket_region != region:
            continue

        try:
            tag_response = s3.get_bucket_tagging(Bucket=name)
            tags = _tags_to_dict(tag_response.get("TagSet"))
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in {"NoSuchTagSet", "AccessDenied", "AccessDeniedException"}:
                tags = {}
            else:
                _raise_from_client_error(exc)

        lifecycle = _s3_lifecycle(s3, name)
        resources.append(
            _resource(
                service="s3",
                resource_type="bucket",
                resource_id=name,
                resource_name=name,
                region=bucket_region,
                status="available",
                configuration={
                    "location_constraint": bucket_region,
                    "lifecycle": lifecycle,
                    "has_lifecycle_policy": lifecycle is not None,
                },
                tags=tags,
                metadata={
                    "creation_date": bucket.get("CreationDate").isoformat()
                    if bucket.get("CreationDate")
                    else None,
                },
            )
        )
    return resources


def _scan_rds_instances(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    rds = session.client("rds", region_name=region)
    paginator = rds.get_paginator("describe_db_instances")
    resources: list[dict[str, Any]] = []

    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            arn = db.get("DBInstanceArn", "")
            tags: dict[str, str] = {}
            try:
                tag_response = rds.list_tags_for_resource(ResourceName=arn)
                tags = _tags_to_dict(tag_response.get("TagList"))
            except ClientError:
                tags = {}

            identifier = db.get("DBInstanceIdentifier", "")
            resources.append(
                _resource(
                    service="rds",
                    resource_type="db_instance",
                    resource_id=identifier,
                    resource_name=_name_from_tags(tags, identifier),
                    region=region,
                    status=db.get("DBInstanceStatus", "unknown"),
                    configuration={
                        "engine": db.get("Engine"),
                        "engine_version": db.get("EngineVersion"),
                        "instance_class": db.get("DBInstanceClass"),
                        "allocated_storage_gb": db.get("AllocatedStorage"),
                        "storage_type": db.get("StorageType"),
                        "storage_encrypted": db.get("StorageEncrypted"),
                        "multi_az": db.get("MultiAZ"),
                        "publicly_accessible": db.get("PubliclyAccessible"),
                        "availability_zone": db.get("AvailabilityZone"),
                        "endpoint": db.get("Endpoint", {}).get("Address") if db.get("Endpoint") else None,
                        "port": db.get("Endpoint", {}).get("Port") if db.get("Endpoint") else None,
                        "backup_retention_period": db.get("BackupRetentionPeriod"),
                        "preferred_backup_window": db.get("PreferredBackupWindow"),
                        "deletion_protection": db.get("DeletionProtection"),
                    },
                    tags=tags,
                    metadata={
                        "arn": arn,
                        "instance_create_time": db.get("InstanceCreateTime").isoformat()
                        if db.get("InstanceCreateTime")
                        else None,
                    },
                )
            )
    return resources


def _scan_cloudwatch_metrics(session: boto3.Session, region: str) -> list[dict[str, Any]]:
    cloudwatch = session.client("cloudwatch", region_name=region)
    resources: list[dict[str, Any]] = []

    for namespace in CLOUDWATCH_NAMESPACES:
        paginator = cloudwatch.get_paginator("list_metrics")
        collected = 0
        truncated = False
        for page in paginator.paginate(Namespace=namespace):
            for metric in page.get("Metrics", []):
                if collected >= CLOUDWATCH_METRICS_PER_NAMESPACE:
                    truncated = True
                    break
                metric_name = metric.get("MetricName", "")
                dimensions = metric.get("Dimensions", [])
                dimension_key = ",".join(
                    f"{item.get('Name')}={item.get('Value')}" for item in dimensions
                )
                resource_id = f"{namespace}:{metric_name}:{dimension_key or 'none'}"
                resources.append(
                    _resource(
                        service="cloudwatch",
                        resource_type="metric",
                        resource_id=resource_id,
                        resource_name=metric_name,
                        region=region,
                        status="available",
                        configuration={
                            "namespace": namespace,
                            "metric_name": metric_name,
                            "dimensions": dimensions,
                        },
                        tags={},
                        metadata={"truncated_namespace": False},
                    )
                )
                collected += 1
            if truncated:
                resources.append(
                    _resource(
                        service="cloudwatch",
                        resource_type="metric_summary",
                        resource_id=f"{namespace}:truncated",
                        resource_name=f"{namespace} metrics truncated",
                        region=region,
                        status="truncated",
                        configuration={
                            "namespace": namespace,
                            "returned": collected,
                            "limit": CLOUDWATCH_METRICS_PER_NAMESPACE,
                        },
                        tags={},
                        metadata={"note": "Additional metrics exist but were not listed."},
                    )
                )
                break
    return resources


def scan_region(region: str, session: boto3.Session | None = None) -> dict[str, Any]:
    """Discover AWS resources in a region. Read-only: describe/list/get only."""
    session = session or create_session()
    identity = _sts_identity(session)
    _assert_valid_region(session, region)

    errors: list[dict[str, str]] = []
    resources: list[dict[str, Any]] = []
    resources.extend(_safe_collect(errors, "ec2", lambda: _scan_ec2_instances(session, region)))
    resources.extend(_safe_collect(errors, "ebs", lambda: _scan_ebs_volumes(session, region)))
    resources.extend(_safe_collect(errors, "elastic_ip", lambda: _scan_elastic_ips(session, region)))
    resources.extend(_safe_collect(errors, "s3", lambda: _scan_s3_buckets(session, region)))
    resources.extend(_safe_collect(errors, "rds", lambda: _scan_rds_instances(session, region)))
    resources.extend(
        _safe_collect(errors, "cloudwatch", lambda: _scan_cloudwatch_metrics(session, region))
    )

    counts: dict[str, int] = {}
    for item in resources:
        key = f"{item['service']}:{item['resource_type']}"
        counts[key] = counts.get(key, 0) + 1

    return {
        "region": region,
        "account_id": identity["account_id"],
        "caller_arn": identity["arn"],
        "scanned_at": _utc_now(),
        "resource_count": len(resources),
        "counts_by_type": counts,
        "resources": resources,
        "partial_errors": errors,
    }
