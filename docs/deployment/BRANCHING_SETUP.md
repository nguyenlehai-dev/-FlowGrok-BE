# FlowGrok BE Branching Setup

Repo backend hiện chưa có lịch sử commit hợp lệ để chạy release flow `staging -> prod`.

## Mục tiêu

- tạo commit đầu tiên trên `main`
- đẩy lại remote branch chuẩn
- tạo hai branch release:
  - `staging`
  - `prod`

## Các bước đề xuất

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
git add .
git commit -m "chore: bootstrap flowgrok backend"
git branch -M main
git push -u origin main
git checkout -b staging
git push -u origin staging
git checkout -b prod main
git push -u origin prod
git checkout staging
```

Sau khi hoàn tất, có thể dùng:

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
./scripts/promote-branch.sh staging prod
```
