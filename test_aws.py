import boto3

sts = boto3.client("sts")

response = sts.get_caller_identity()

print("AWS Account:", response["Account"])
print("User ARN:", response["Arn"])