def processAll(prefix_name, Ao, theta):
    
    from dem import Elevation, FlowDirectionD8, GeographicArea, Area, GeographicFlowLength, Ksi, ScaledRelief
    
    elevation_name = prefix_name + "_dem_15s"
    area_name = prefix_name + "_acc_15s"
    d8_name = prefix_name + "_dir_15s"
    
    elevation = Elevation(gdal_filename = elevation_name)
    area = Area(gdal_filename = area_name)
    d8 = FlowDirectionD8(gdal_filename = d8_name)
    
    area = GeographicArea(flow_direction = d8, sorted_indexes = area.sort())
    ksi = Ksi(area = area, flow_direction = d8, theta = theta, Ao = Ao)
    flow_length = GeographicFlowLength(flow_direction = d8, sorted_indexes = area.sort())
    relief = ScaledRelief(flow_direction = d8, elevation = elevation, flow_length = flow_length, Ao = Ao, theta = theta)
    
    elevation.save(prefix_name + "_elevation")
    d8.save(prefix_name + "_flow_direction")
    area.save(prefix_name + "_area")
    ksi.save(prefix_name + "_ksi_" + str(Ao) + "_" + str(theta))
    flow_length.save(prefix_name + "_flow_length")
    relief.save(prefix_name + "_relief_" + str(Ao) + "_" + str(theta))
    
    