# AWS Systems Manager Parameter Store

`awsssm` keeps each secret in a `SecureString` parameter of AWS Systems Manager
Parameter Store, in one region of the AWS account the identity of the pod
belongs to.

```yaml
secretStore:
  kind: awsssm
  prefix: hush
  aws:
    region: us-east-1
    # optional customer managed KMS key
    kmsKeyId: ""
accessManager:
  workloadIdentity:
    aws:
      irsa: arn:aws:iam::<account>:role/hush-am
```

## Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:PutParameter",
        "ssm:GetParameter",
        "ssm:DeleteParameter"
      ],
      "Resource": "arn:aws:ssm:<region>:<account>:parameter/<prefix>/*"
    }
  ]
}
```

With `secretStore.aws.kmsKeyId`, add the key, which its key policy must allow,
directly or by delegating to IAM:

```json
{
  "Effect": "Allow",
  "Action": ["kms:Encrypt", "kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>"
}
```

A parameter of the standard tier is encrypted with `kms:Encrypt`, one of the
advanced tier with `kms:GenerateDataKey`, and the store lets AWS pick the tier,
so the role needs both. Without a key, Parameter Store encrypts with the AWS
managed key `aws/ssm`, which needs no KMS permission.

Each AWS store also calls `sts:GetCallerIdentity` when it is set up, to learn
the account. AWS allows that call to every identity, so it needs no permission.

## Identity

The same as for [AWS Secrets Manager](awssm.md#identity).

## Notes

- The prefix may not start with `aws` or `ssm`, which Parameter Store
  reserves, and holds at most 9 `/`-separated segments.
- A value is at most 8 KB. The store creates parameters with
  Intelligent-Tiering, so a parameter becomes an advanced one, which AWS charges
  for, when its value is over 4 KB, or once the account holds 10,000 standard
  parameters in the region.
- The KMS key applies to every write, existing parameters included.
