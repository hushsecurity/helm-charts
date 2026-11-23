# AWS Secrets Manager

`awssm` keeps each secret in an AWS Secrets Manager secret, in one region of
the AWS account the identity of the pod belongs to.

```yaml
secretStore:
  kind: awssm
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
        "secretsmanager:CreateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DeleteSecret"
      ],
      "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:<prefix>/*"
    }
  ]
}
```

With `secretStore.aws.kmsKeyId`, add the key, which its key policy must allow,
directly or by delegating to IAM:

```json
{
  "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>"
}
```

Without it, Secrets Manager encrypts with the AWS managed key
`aws/secretsmanager`, which needs no KMS permission.

Each AWS store also calls `sts:GetCallerIdentity` when it is set up, to learn
the account. AWS allows that call to every identity, so it needs no permission.

## Identity

Choose one:

- **IRSA, on EKS.** Set `accessManager.workloadIdentity.aws.irsa` to the ARN of
  a role that trusts the cluster's OIDC provider for the service account. See
  [IAM roles for service accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html).
- **An IAM role, on any cluster.** Set
  `accessManager.workloadIdentity.aws.oidc.role` to the role ARN. The pod
  assumes it with its own service account token. Register the cluster's OIDC
  issuer as an IAM OIDC identity provider with the audience
  `sts.amazonaws.com`, and let the role be assumed over it:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Federated": "arn:aws:iam::<account>:oidc-provider/<issuer>"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
          "StringEquals": {
            "<issuer>:sub": "system:serviceaccount:<namespace>:<service-account>",
            "<issuer>:aud": "sts.amazonaws.com"
          }
        }
      }
    ]
  }
  ```

  `<issuer>` is the issuer URL without `https://`. AWS reads the issuer's
  discovery document and keys, so they must be reachable over public HTTPS.
  Another audience goes in `accessManager.workloadIdentity.aws.oidc.audience`.
  The install fails if the role is combined with `irsa`, or in `hush-am` with
  the deprecated `secretStore.aws.irsa` or `containerRegistry.aws.irsa`.

In `hush-am`, `secretStore.aws.irsa` still works in place of
`accessManager.workloadIdentity.aws.irsa`, but is deprecated.

## Notes

- The KMS key applies to secrets created after it is set. Existing secrets keep
  the key they were created with.
- A secret the store deletes is deleted at once, without a recovery window.
