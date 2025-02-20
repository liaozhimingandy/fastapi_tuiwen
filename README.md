# django_hip_service

#### 参考链接

```
官方文档：https://pdm-project.org/2.12/
其它文档：https://blog.csdn.net/aichaoxy/article/details/134733841
```

### 依赖
```python
pdm export -o requirements.txt --without-hashes
```

#### 参考链接

```
官方文档：https://pdm-project.org/2.12/
其它文档：https://blog.csdn.net/aichaoxy/article/details/134733841
```

### 首次安装依赖
```python
pdm install
```

### 依赖
```python
pdm export -o requirements.txt --without-hashes
```

#### 增加依赖库
```python
# 使用pdm add命令能为当前目录的项目添加依赖库，添加到默认环境, 如
eg: pdm add requests
```

#### 依赖库分组
pdm为依赖库的管理提供了分组能力，常见的组有dev（开发专属）、prod（生产专属）等等，也可以自定义创建组。
```python
# 添加pytest依赖，到dev环境，并加入分组test
pdm add pytest -dG test
# 添加到测试环境
pdm add pytest -d
```
